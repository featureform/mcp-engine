package proxy

import (
	"bytes"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

// mockReadCloser is a simple mock for io.ReadCloser
type mockReadCloser struct {
	io.Reader
}

func (m mockReadCloser) Close() error {
	return nil
}

func TestSSEConnectionAndEndpointEvent(t *testing.T) {
	// Create a mock SSE server
	sseServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Verify the request headers
		if r.Header.Get("Accept") != "text/event-stream" {
			t.Errorf("Expected Accept header to be text/event-stream, got %s", r.Header.Get("Accept"))
		}

		// Set SSE headers
		w.Header().Set("Content-Type", "text/event-stream")
		w.Header().Set("Cache-Control", "no-cache")
		w.Header().Set("Connection", "keep-alive")
		w.WriteHeader(http.StatusOK)

		// Send the endpoint event
		postURL := "http://localhost:12345/post"
		fmt.Fprintf(w, "event: endpoint\ndata: %s\n\n", postURL)

		// Flush to ensure the message is sent immediately
		if f, ok := w.(http.Flusher); ok {
			f.Flush()
		}

		// Keep the connection open for a bit
		time.Sleep(300 * time.Millisecond)

		// Send a message event
		fmt.Fprintf(w, "event: message\ndata: {\"jsonrpc\":\"2.0\",\"result\":\"test response\"}\n\n")
		if f, ok := w.(http.Flusher); ok {
			f.Flush()
		}

		// Keep the connection open until test completes
		select {
		case <-r.Context().Done():
			return
		case <-time.After(1 * time.Second):
			return
		}
	}))
	defer sseServer.Close()

	// Create a mock POST server
	postReceived := make(chan string, 1)
	postServer := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Verify the request method and headers
		if r.Method != "POST" {
			t.Errorf("Expected POST request, got %s", r.Method)
		}

		// Read the request body
		body, err := io.ReadAll(r.Body)
		if err != nil {
			t.Errorf("Error reading request body: %v", err)
		}

		// Send the body to our channel for verification
		postReceived <- string(body)

		// Return a success response
		w.WriteHeader(http.StatusOK)
	}))
	defer postServer.Close()

	// Create buffers for testing stdin/stdout
	inputBuffer := strings.NewReader("{\"jsonrpc\":\"2.0\",\"method\":\"test\",\"params\":{}}\n")
	outputBuffer := &bytes.Buffer{}
	
	// Create a test logger that writes to a buffer
	var logBuffer bytes.Buffer
	testLogger := log.New(&logBuffer, "TEST: ", 0)
	
	// Create a proxy server with our test servers
	proxy := &ProxyServer{
		ServerURL:    sseServer.URL,
		Logger:       testLogger,
		InputReader:  inputBuffer,
		OutputWriter: outputBuffer,
		DoneChan:     make(chan struct{}),
		ErrorChan:    make(chan error, 1),
		HTTPClient:   http.DefaultClient,
	}
	
	// Start the proxy in a goroutine
	go func() {
		proxy.Start()
	}()
	
	// Wait for the POST request to be received or timeout
	var receivedMessage string
	select {
	case receivedMessage = <-postReceived:
		// Got the message
	case <-time.After(2 * time.Second):
		t.Fatal("Timed out waiting for POST request")
	}
	
	// Verify the POST message
	expectedMessage := "{\"jsonrpc\":\"2.0\",\"method\":\"test\",\"params\":{}}"
	if receivedMessage != expectedMessage {
		t.Errorf("Expected POST message %s, got %s", expectedMessage, receivedMessage)
	}
	
	// Wait for the SSE message to be processed
	time.Sleep(500 * time.Millisecond)
	
	// Stop the proxy
	proxy.Stop()
	
	// Verify the output contains the expected message
	output := outputBuffer.String()
	expectedOutput := "{\"jsonrpc\":\"2.0\",\"result\":\"test response\"}"
	if !strings.Contains(output, expectedOutput) {
		t.Errorf("Expected output to contain %s, got %s", expectedOutput, output)
	}

	// Verify that the proxy updated its PostURL
	if !strings.Contains(proxy.PostURL, "localhost:12345/post") {
		t.Errorf("Expected PostURL to be set to the endpoint value, got %s", proxy.PostURL)
	}
}

func TestErrorHandling(t *testing.T) {
	// Test with a URL that doesn't exist
	proxy := NewProxyServer("http://localhost:12345", nil)
	
	// Use test buffers
	proxy.InputReader = strings.NewReader("test message\n")
	proxy.OutputWriter = &bytes.Buffer{}
	
	// Start the proxy
	errorChan := make(chan error, 1)
	go func() {
		errorChan <- proxy.Start()
	}()
	
	// Wait for the error
	var err error
	select {
	case err = <-errorChan:
		// Got an error, as expected
	case <-time.After(2 * time.Second):
		t.Fatalf("Timed out waiting for error")
	}
	
	// Verify the error is about connection
	if err == nil || !strings.Contains(err.Error(), "error connecting to SSE endpoint") {
		t.Errorf("Expected SSE connection error, got: %v", err)
	}
}

func TestServerErrors(t *testing.T) {
	// Create a mock server that returns a 500 error
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer server.Close()
	
	// Create a proxy with the test server
	proxy := NewProxyServer(server.URL, nil)
	proxy.InputReader = strings.NewReader("test message\n")
	proxy.OutputWriter = &bytes.Buffer{}
	
	// Start the proxy and wait for error
	errorChan := make(chan error, 1)
	go func() {
		errorChan <- proxy.Start()
	}()
	
	// Verify error about server status
	var err error
	select {
	case err = <-errorChan:
		// Got an error, as expected
	case <-time.After(2 * time.Second):
		t.Fatalf("Timed out waiting for error")
	}
	
	if err == nil || !strings.Contains(err.Error(), "server returned error status for SSE connection") {
		t.Errorf("Expected server error status, got: %v", err)
	}
}

func TestMalformedSSEEvents(t *testing.T) {
	// Create a mock server that returns malformed SSE
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		w.WriteHeader(http.StatusOK)
		
		// Send malformed SSE (missing event type)
		fmt.Fprintln(w, "data: malformed message")
		fmt.Fprintln(w, "")
		if f, ok := w.(http.Flusher); ok {
			f.Flush()
		}
	}))
	defer server.Close()
	
	// Create a test logger that writes to a buffer
	var logBuffer bytes.Buffer
	testLogger := log.New(&logBuffer, "TEST: ", 0)
	
	// Create a proxy with the test server
	proxy := NewProxyServer(server.URL, testLogger)
	proxy.InputReader = strings.NewReader("test message\n")
	outputBuffer := &bytes.Buffer{}
	proxy.OutputWriter = outputBuffer
	
	// Start the proxy
	go func() {
		proxy.Start()
	}()
	
	// Give it time to process
	time.Sleep(500 * time.Millisecond)
	
	// Stop the proxy
	proxy.Stop()
	
	// Verify the log contains a message about the unknown event type
	logOutput := logBuffer.String()
	if !strings.Contains(logOutput, "Unknown event type") {
		t.Errorf("Expected log to mention 'Unknown event type', got: %s", logOutput)
	}
	
	// Verify no output for malformed event
	output := outputBuffer.String()
	if strings.Contains(output, "malformed message") {
		t.Errorf("Expected no output for malformed event, got: %s", output)
	}
}
