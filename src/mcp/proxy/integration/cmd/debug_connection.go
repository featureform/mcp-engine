package main

import (
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strings"
	"time"
)

// This is a standalone utility to debug connections to the MCP server
// You can run it directly with: go run integration/debug_connection.go

func main() {
	// Default URL if not provided
	serverURL := "http://localhost:8000/sse"
	if len(os.Args) > 1 {
		serverURL = os.Args[1]
	}

	fmt.Printf("Connecting to SSE endpoint: %s\n", serverURL)

	// Configure an HTTP client
	client := &http.Client{
		Timeout: 0, // No timeout for SSE connections
	}

	// Configure an HTTP request for SSE
	req, err := http.NewRequest("GET", serverURL, nil)
	if err != nil {
		log.Fatalf("Error creating SSE request: %v", err)
	}

	// Set headers for SSE
	req.Header.Set("Accept", "text/event-stream")
	req.Header.Set("Cache-Control", "no-cache")
	req.Header.Set("Connection", "keep-alive")

	// Make the request
	fmt.Println("Sending request...")
	resp, err := client.Do(req)
	if err != nil {
		log.Fatalf("Error connecting to SSE endpoint: %v", err)
	}
	defer resp.Body.Close()

	// Check response status
	fmt.Printf("Connected, status: %s\n", resp.Status)
	for name, values := range resp.Header {
		fmt.Printf("Header: %s = %s\n", name, strings.Join(values, ", "))
	}

	// Set a timeout for reading from the SSE stream
	totalTimeout := 30 * time.Second
	// deadline := time.Now().Add(totalTimeout)

	fmt.Printf("Waiting for events (timeout: %v)...\n", totalTimeout)

	// Read the first bytes from the response to verify connection
	buffer := make([]byte, 1024)
	readTimeout := time.After(totalTimeout)

	// Create a channel to receive the read result
	readChan := make(chan struct {
		n   int
		err error
	})

	// Read in a goroutine to handle timeouts
	go func() {
		n, err := resp.Body.Read(buffer)
		readChan <- struct {
			n   int
			err error
		}{n, err}
	}()

	// Wait for either a read result or a timeout
	select {
	case result := <-readChan:
		if result.err != nil && result.err != io.EOF {
			fmt.Printf("Error reading from SSE stream: %v\n", result.err)
		} else if result.n > 0 {
			fmt.Printf("Received %d bytes:\n%s\n", result.n, string(buffer[:result.n]))
		} else {
			fmt.Println("No data received before connection closed")
		}
	case <-readTimeout:
		fmt.Println("Timeout waiting for data")
	}

	fmt.Println("Check complete")
}
