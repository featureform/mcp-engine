package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"strings"
	"time"
)

// InitializeRequest represents the MCP initialization message
// using the correct format for 2024-11-05
type InitializeRequest struct {
	JSONRPC string `json:"jsonrpc"`
	ID      string `json:"id"`
	Method  string `json:"method"`
	Params  struct {
		ProtocolVersion string `json:"protocolVersion"`
		ClientInfo      struct {
			Name    string `json:"name"`
			Version string `json:"version"`
		} `json:"clientInfo"`
		Capabilities struct{} `json:"capabilities"`
	} `json:"params"`
}

func main() {
	// Default URL
	serverURL := "http://localhost:8000/sse"
	if len(os.Args) > 1 {
		serverURL = os.Args[1]
	}

	fmt.Printf("Testing MCP connection to: %s\n", serverURL)

	// Step 1: Create the SSE connection
	client := &http.Client{Timeout: 0}
	req, err := http.NewRequest("GET", serverURL, nil)
	if err != nil {
		log.Fatalf("Error creating request: %v", err)
	}

	// Set standard SSE headers
	req.Header.Set("Accept", "text/event-stream")
	req.Header.Set("Cache-Control", "no-cache")
	req.Header.Set("Connection", "keep-alive")

	// Make the request
	fmt.Println("Connecting to SSE endpoint...")
	resp, err := client.Do(req)
	if err != nil {
		log.Fatalf("Error connecting: %v", err)
	}
	defer resp.Body.Close()

	// Verify connection
	fmt.Printf("Connected, status: %s\n", resp.Status)

	// Process SSE events in background
	go func() {
		scanner := bufio.NewScanner(resp.Body)
		var eventType, data string
		inEvent := false

		for scanner.Scan() {
			line := scanner.Text()
			fmt.Printf("RAW: %s\n", line)

			// Empty line marks the end of an event
			if line == "" {
				if inEvent {
					fmt.Printf("EVENT: type=%s data=%s\n", eventType, data)
					if eventType == "endpoint" {
						// We received the POST URL
						postURL := data
						if strings.HasPrefix(postURL, "/") {
							// It's a relative URL, extract the base
							parts := strings.Split(serverURL, "/")
							baseURL := parts[0] + "//" + parts[2]
							postURL = baseURL + postURL
						}
						fmt.Printf("POST URL: %s\n", postURL)

						// Now send an initialize request to the POST URL
						sendInitializeRequest(postURL)
					}
					eventType = ""
					data = ""
					inEvent = false
				}
				continue
			}

			// Check for event type or data
			if strings.HasPrefix(line, "event:") {
				eventType = strings.TrimSpace(strings.TrimPrefix(line, "event:"))
				inEvent = true
			} else if strings.HasPrefix(line, "data:") {
				inEvent = true
				if data != "" {
					data += "\n"
				}
				data += strings.TrimSpace(strings.TrimPrefix(line, "data:"))
			}
		}

		if err := scanner.Err(); err != nil {
			fmt.Printf("Error reading SSE: %v\n", err)
		}
	}()

	// Wait for user to exit
	fmt.Println("Press Enter to exit")
	bufio.NewReader(os.Stdin).ReadBytes('\n')
	fmt.Println("Exiting")
}

func sendInitializeRequest(postURL string) {
	// Create a properly formatted initialization request
	req := InitializeRequest{
		JSONRPC: "2.0",
		ID:      "1",
		Method:  "initialize",
	}
	req.Params.ProtocolVersion = "mcp/2024-11-05"
	req.Params.ClientInfo.Name = "debug-client"
	req.Params.ClientInfo.Version = "1.0.0"

	// Marshal to JSON
	data, err := json.Marshal(req)
	if err != nil {
		fmt.Printf("Error marshaling request: %v\n", err)
		return
	}

	fmt.Printf("Sending initialize request: %s\n", string(data))

	// Send the request
	httpClient := &http.Client{Timeout: 10 * time.Second}
	resp, err := httpClient.Post(postURL, "application/json", bytes.NewBuffer(data))
	if err != nil {
		fmt.Printf("Error sending request: %v\n", err)
		return
	}
	defer resp.Body.Close()

	// Read the response
	buf := new(bytes.Buffer)
	buf.ReadFrom(resp.Body)
	response := buf.String()

	fmt.Printf("Response status: %s\n", resp.Status)
	fmt.Printf("Response body: %s\n", response)
}
