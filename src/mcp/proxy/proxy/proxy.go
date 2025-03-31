package proxy

import (
	"bufio"
	"bytes"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"os"
	"strings"
	"sync"
	"time"
)

// ProxyServer represents an SSE proxy server
type ProxyServer struct {
	ServerURL    string      // The base URL for the SSE endpoint
	PostURL      string      // URL for the POST endpoint (received from server)
	Logger       *log.Logger
	HTTPClient   *http.Client
	InputReader  io.Reader
	OutputWriter io.Writer
	DoneChan     chan struct{}
	ErrorChan    chan error
	WaitGroup    sync.WaitGroup
	Connected    bool           // Flag to track if we've established the connection
	Mutex        sync.Mutex     // Mutex to protect concurrent access to state
	// Add a connection notification channel
	ConnectedChan chan struct{} // Channel to signal when connection is established
}

// NewProxyServer creates a new SSE proxy server
func NewProxyServer(serverURL string, logger *log.Logger) *ProxyServer {
	if logger == nil {
		logger = log.New(os.Stderr, "SSE-PROXY: ", log.Ldate|log.Ltime|log.Lshortfile)
	}

	return &ProxyServer{
		ServerURL:    serverURL,
		PostURL:      "",  // This will be populated from the endpoint event
		Logger:       logger,
		InputReader:  os.Stdin,
		OutputWriter: os.Stdout,
		DoneChan:     make(chan struct{}),
		ErrorChan:    make(chan error, 1),
		HTTPClient: &http.Client{
			Timeout: 0, // No timeout, let the connection persist
			Transport: &http.Transport{
				IdleConnTimeout:     90 * time.Second,
				MaxIdleConns:        100,
				MaxIdleConnsPerHost: 100,
			},
		},
		Connected:     false,
		ConnectedChan: make(chan struct{}),
	}
}

// Start begins the proxy operation
func (p *ProxyServer) Start() error {
	inputChan := make(chan string)

	// Start a goroutine to read from input
	p.WaitGroup.Add(1)
	go func() {
		defer p.WaitGroup.Done()
		defer close(inputChan)

		scanner := bufio.NewScanner(p.InputReader)
		for scanner.Scan() {
			select {
			case <-p.DoneChan:
				return
			default:
				line := scanner.Text()
				p.Logger.Printf("Read from stdin: %s", line)
				inputChan <- line
			}
		}
		if err := scanner.Err(); err != nil {
			p.Logger.Printf("Error reading from input: %v", err)
			p.ErrorChan <- fmt.Errorf("input read error: %w", err)
		}
	}()

	// Start the SSE connection handler
	p.WaitGroup.Add(1)
	go p.handleSSEConnection()

	// Start the HTTP message sender
	p.WaitGroup.Add(1)
	go p.handleMessageSending(inputChan)

	// Return first error encountered
	return <-p.ErrorChan
}

// Stop gracefully stops the proxy
func (p *ProxyServer) Stop() {
	close(p.DoneChan)
	p.WaitGroup.Wait()
	p.Logger.Println("Proxy terminated")
}

// handleSSEConnection establishes and maintains the SSE connection
func (p *ProxyServer) handleSSEConnection() {
	defer p.WaitGroup.Done()

	// Configure an HTTP request for SSE
	req, err := http.NewRequest("GET", p.ServerURL, nil)
	if err != nil {
		p.ErrorChan <- fmt.Errorf("error creating SSE request: %w", err)
		return
	}

	// Set headers for SSE
	req.Header.Set("Accept", "text/event-stream")
	req.Header.Set("Cache-Control", "no-cache")
	req.Header.Set("Connection", "keep-alive")

	// Make the request
	p.Logger.Println("Establishing SSE connection to server:", p.ServerURL)
	resp, err := p.HTTPClient.Do(req)
	if err != nil {
		p.ErrorChan <- fmt.Errorf("error connecting to SSE endpoint: %w", err)
		return
	}
	defer resp.Body.Close()

	// Check response status
	if resp.StatusCode != http.StatusOK {
		p.ErrorChan <- fmt.Errorf("server returned error status for SSE connection: %s", resp.Status)
		return
	}

	p.Logger.Printf("Connected to SSE endpoint, status: %s", resp.Status)

	// Process the SSE stream
	scanner := bufio.NewScanner(resp.Body)
	var eventType, data string
	inEvent := false

	for scanner.Scan() {
		select {
		case <-p.DoneChan:
			return
		default:
			line := scanner.Text()
			p.Logger.Printf("Received SSE line: %s", line)
			
			// Empty line marks the end of an event
			if line == "" {
				if inEvent {
					p.processEvent(eventType, data)
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
				p.Logger.Printf("Parsed event type: %s", eventType)
			} else if strings.HasPrefix(line, "data:") {
				inEvent = true
				if data != "" {
					data += "\n"
				}
				data += strings.TrimSpace(strings.TrimPrefix(line, "data:"))
				p.Logger.Printf("Parsed data: %s", data)
			}
		}
	}

	// Check if we exited the loop due to an error
	if err := scanner.Err(); err != nil {
		p.ErrorChan <- fmt.Errorf("error reading SSE stream: %w", err)
		return
	}

	// If we get here, the server closed the connection normally
	p.Logger.Println("Server closed the SSE connection")
	p.ErrorChan <- fmt.Errorf("server closed the SSE connection")
}

// processEvent handles different SSE event types
func (p *ProxyServer) processEvent(eventType, data string) {
	p.Logger.Printf("Processing SSE event: %s, data: %s", eventType, data)

	switch eventType {
	case "endpoint":
		// Store the POST endpoint URL
		// Handle relative URLs by prepending the base URL
		postURL := data
		if strings.HasPrefix(postURL, "/") {
			// Extract the base URL from the server URL
			baseURL, err := extractBaseURL(p.ServerURL)
			if err != nil {
				p.Logger.Printf("Error extracting base URL: %v", err)
			} else {
				postURL = baseURL + postURL
				p.Logger.Printf("Converted relative URL to absolute: %s", postURL)
			}
		}

		p.Mutex.Lock()
		p.PostURL = postURL
		p.Connected = true
		p.Mutex.Unlock()
		p.Logger.Printf("Received POST endpoint: %s", postURL)
		
		// Signal that we're connected
		select {
		case p.ConnectedChan <- struct{}{}:
			p.Logger.Printf("Signaled connection established")
		default:
			p.Logger.Printf("Channel already signaled or closed")
		}
		
	case "message":
		// Write the message data to stdout
		p.Logger.Printf("Received message: %s", data)
		// Print a hex/byte dump of the message to help debug
		p.Logger.Printf("Raw message bytes: %x", []byte(data))
		fmt.Fprintln(p.OutputWriter, data)
		
	default:
		p.Logger.Printf("Unknown event type: %s", eventType)
	}
}

// handleMessageSending sends messages from stdin to the HTTP endpoint
func (p *ProxyServer) handleMessageSending(inputChan <-chan string) {
	defer p.WaitGroup.Done()

	for {
		select {
		case <-p.DoneChan:
			return
		case input, ok := <-inputChan:
			if !ok {
				p.Logger.Println("Input channel closed, stopping sender")
				return
			}

			// Wait for endpoint URL with a timeout
			connected := p.waitForConnection(30 * time.Second)
			if !connected {
				p.Logger.Println("Timed out waiting for POST endpoint URL, proceeding anyway...")
			}

			// Send the message
			if err := p.sendMessage(input); err != nil {
				p.Logger.Printf("Error sending message: %v", err)
				// Don't exit on send errors, just log them
			}
		}
	}
}

// waitForConnection waits for the connection to be established with a timeout
func (p *ProxyServer) waitForConnection(timeout time.Duration) bool {
	if p.isConnected() {
		return true
	}

	p.Logger.Printf("Waiting for POST endpoint URL (timeout: %v)...", timeout)
	
	select {
	case <-p.ConnectedChan:
		p.Logger.Println("Connection established signal received")
		return true
	case <-time.After(timeout):
		p.Logger.Println("Timed out waiting for connection")
		return false
	case <-p.DoneChan:
		p.Logger.Println("Done signal received while waiting for connection")
		return false
	}
}

// isConnected checks if we have received the POST endpoint URL
func (p *ProxyServer) isConnected() bool {
	p.Mutex.Lock()
	defer p.Mutex.Unlock()
	result := p.Connected && p.PostURL != ""
	p.Logger.Printf("Connection check: %v (Connected: %v, PostURL: %s)", 
		result, p.Connected, p.PostURL)
	return result
}

// extractBaseURL extracts the base URL (scheme + host) from a full URL
func extractBaseURL(fullURL string) (string, error) {
	parsedURL, err := url.Parse(fullURL)
	if err != nil {
		return "", fmt.Errorf("failed to parse URL: %w", err)
	}

	// Return scheme + host
	baseURL := fmt.Sprintf("%s://%s", parsedURL.Scheme, parsedURL.Host)
	return baseURL, nil
}

// sendMessage sends a message to the POST endpoint
func (p *ProxyServer) sendMessage(message string) error {
	p.Mutex.Lock()
	postURL := p.PostURL
	p.Mutex.Unlock()

	if postURL == "" {
		return fmt.Errorf("no POST endpoint URL available")
	}

	// Create the request
	req, err := http.NewRequest("POST", postURL, bytes.NewBufferString(message))
	if err != nil {
		return fmt.Errorf("error creating POST request: %w", err)
	}

	// Set content type for JSON-RPC
	req.Header.Set("Content-Type", "application/json")
	
	// Check for session ID in the URL
	parsedURL, err := url.Parse(postURL)
	if err == nil && parsedURL.Query().Get("session_id") != "" {
		sessionID := parsedURL.Query().Get("session_id")
		p.Logger.Printf("Found session ID in URL: %s", sessionID)
	}

	// Send the request
	p.Logger.Printf("Sending message to POST endpoint: %s", message)
	resp, err := p.HTTPClient.Do(req)
	if err != nil {
		return fmt.Errorf("error sending POST request: %w", err)
	}
	defer resp.Body.Close()

	// Check response status
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("server returned error status for POST: %s", resp.Status)
	}

	p.Logger.Printf("Message sent successfully, status: %s", resp.Status)
	return nil
}
