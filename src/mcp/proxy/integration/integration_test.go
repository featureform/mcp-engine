package integration

import (
	"bytes"
	"encoding/json"
	"log"
	"os"
	"strings"
	"testing"
	"time"

	"github.com/featureform/stdiosseproxy/proxy"
)

// InitializeRequest represents the MCP initialization message
// according to the 2024-11-05 specification
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

// createInitializeRequest creates a properly formatted initialization message
func createInitializeRequest() InitializeRequest {
	req := InitializeRequest{
		JSONRPC: "2.0",
		ID:      "1",
		Method:  "initialize",
	}
	req.Params.ProtocolVersion = "mcp/2024-11-05"
	req.Params.ClientInfo.Name = "stdiosseproxy-test"
	req.Params.ClientInfo.Version = "1.0.0"

	return req
}

// TestInitializationFlow tests the initialization flow with a real MCP server
func TestInitializationFlow(t *testing.T) {
	// Skip this test if the integration flag is not provided
	if os.Getenv("RUN_INTEGRATION_TESTS") != "1" {
		t.Skip("Skipping integration test. Set RUN_INTEGRATION_TESTS=1 to run.")
	}

	// URL of the actual MCP server - fix the URL format
	serverURL := "http://localhost:8000/sse"

	// Create a buffer for the input (to the server)
	initReq := createInitializeRequest()
	initReqBytes, err := json.Marshal(initReq)
	if err != nil {
		t.Fatalf("Failed to marshal initialize request: %v", err)
	}

	inputBuffer := bytes.NewBufferString(string(initReqBytes) + "\n")

	// Create a buffer for the output (from the server)
	outputBuffer := &bytes.Buffer{}

	// Create a logger that prints to stdout for easier debugging
	testLogger := log.New(os.Stdout, "INTEGRATION-TEST: ", log.Ltime)

	// Create the proxy server
	proxyServer := proxy.NewProxyServer(serverURL, testLogger)
	proxyServer.InputReader = inputBuffer
	proxyServer.OutputWriter = outputBuffer

	// Start the proxy in a goroutine
	errChan := make(chan error, 1)
	go func() {
		errChan <- proxyServer.Start()
	}()

	// Wait for a reasonable amount of time for the initialization flow
	// to complete or fail - increased timeout
	var proxyError error
	select {
	case proxyError = <-errChan:
		// If we get an error, log it but continue testing
		t.Logf("Proxy returned error: %v", proxyError)
	case <-time.After(10 * time.Second):
		// If we timeout, that's okay - the proxy is still running
		t.Log("Proxy is still running after 10 seconds")
	}

	// Stop the proxy
	proxyServer.Stop()

	// Debug log current state
	t.Logf("After test - Connected: %v, PostURL: %s",
		proxyServer.Connected, proxyServer.PostURL)

	// Verify the proxy has received the POST endpoint
	if proxyServer.PostURL == "" {
		t.Error("Proxy did not receive a POST endpoint URL")
	} else {
		t.Logf("POST endpoint URL: %s", proxyServer.PostURL)
	}

	// Check the output buffer for a valid response
	output := outputBuffer.String()
	t.Logf("Server response: %s", output)

	// Verify we got a response that looks like a valid JSON-RPC response
	if !strings.Contains(output, "\"jsonrpc\":\"2.0\"") ||
		!strings.Contains(output, "\"id\":\"1\"") {
		t.Error("Did not receive valid JSON-RPC response")
	}

	// Verify that the response is related to initialization
	// This depends on the exact server implementation, but we can at least
	// check for common fields we'd expect in the response
	if !strings.Contains(output, "\"result\"") {
		t.Error("Response does not contain a result field")
	}

	// Try to parse the response to verify it's valid JSON
	var responseMap map[string]interface{}
	if err := json.NewDecoder(strings.NewReader(output)).Decode(&responseMap); err != nil {
		t.Errorf("Failed to parse server response as JSON: %v", err)
	} else {
		// If we can parse it, log the response structure
		t.Logf("Response structure: %+v", responseMap)

		// Check if there's a server field in the result
		if result, ok := responseMap["result"].(map[string]interface{}); ok {
			if server, ok := result["server"].(map[string]interface{}); ok {
				t.Logf("Server name: %v, version: %v",
					server["name"], server["version"])
			}
		}
	}
}

// TestRealMessageExchange tests sending an actual message to the server
// after initialization
func TestRealMessageExchange(t *testing.T) {
	// Skip this test if the integration flag is not provided
	if os.Getenv("RUN_INTEGRATION_TESTS") != "1" {
		t.Skip("Skipping integration test. Set RUN_INTEGRATION_TESTS=1 to run.")
	}

	// URL of the actual MCP server
	serverURL := "http://localhost:8000/sse"

	// First, we need to initialize
	initReq := createInitializeRequest()
	initReqBytes, err := json.Marshal(initReq)
	if err != nil {
		t.Fatalf("Failed to marshal initialize request: %v", err)
	}

	// Create a request for a second message
	echoRequest := map[string]interface{}{
		"jsonrpc": "2.0",
		"id":      "2",
		"method":  "echo",
		"params": map[string]interface{}{
			"message": "Hello, MCP!",
		},
	}
	echoReqBytes, err := json.Marshal(echoRequest)
	if err != nil {
		t.Fatalf("Failed to marshal echo request: %v", err)
	}

	// Create an initialized notification
	initializedNotification := map[string]interface{}{
		"jsonrpc": "2.0",
		"method":  "initialized",
		"params":  struct{}{},
	}
	initializedBytes, err := json.Marshal(initializedNotification)
	if err != nil {
		t.Fatalf("Failed to marshal initialized notification: %v", err)
	}

	// Prepare the input with multiple messages
	inputStr := string(initReqBytes) + "\n" +
		string(initializedBytes) + "\n" +
		string(echoReqBytes) + "\n"

	inputBuffer := bytes.NewBufferString(inputStr)

	// Create a buffer for the output
	outputBuffer := &bytes.Buffer{}

	// Create a logger that prints to stdout for easier debugging
	testLogger := log.New(os.Stdout, "INTEGRATION-TEST: ", log.Ltime)

	// Create the proxy server with a longer timeout
	proxyServer := proxy.NewProxyServer(serverURL, testLogger)
	proxyServer.InputReader = inputBuffer
	proxyServer.OutputWriter = outputBuffer

	// Start the proxy in a goroutine
	errChan := make(chan error, 1)
	go func() {
		errChan <- proxyServer.Start()
	}()

	// Wait for a reasonable amount of time for the message exchange
	// to complete or fail
	var proxyError error
	select {
	case proxyError = <-errChan:
		// If we get an error, log it but continue testing
		t.Logf("Proxy returned error: %v", proxyError)
	case <-time.After(15 * time.Second):
		// If we timeout, that's okay - the proxy is still running
		t.Log("Proxy is still running after 15 seconds")
	}

	// Stop the proxy
	proxyServer.Stop()

	// Debug log current state
	t.Logf("After test - Connected: %v, PostURL: %s",
		proxyServer.Connected, proxyServer.PostURL)

	// Analyze the output
	output := outputBuffer.String()

	// Split the output by newlines to get individual responses
	responses := strings.Split(strings.TrimSpace(output), "\n")
	t.Logf("Received %d responses", len(responses))

	for i, resp := range responses {
		t.Logf("Response %d: %s", i+1, resp)

		// Try to parse each response
		var respMap map[string]interface{}
		if err := json.Unmarshal([]byte(resp), &respMap); err != nil {
			t.Errorf("Failed to parse response as JSON: %v", err)
			continue
		}

		// Check if it has an ID and matches our requests
		if id, ok := respMap["id"].(string); ok {
			switch id {
			case "1":
				t.Log("Found response to initialize request")
			case "2":
				t.Log("Found response to echo request")
				// Check the echo response
				if result, ok := respMap["result"].(map[string]interface{}); ok {
					if message, ok := result["message"].(string); ok {
						if message != "Hello, MCP!" {
							t.Errorf("Echo message mismatch. Expected: 'Hello, MCP!', got: '%s'", message)
						}
					} else {
						t.Error("Echo response doesn't contain expected message field")
					}
				}
			}
		}
	}
}
