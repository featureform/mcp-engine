package mcpengine

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"math"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"sync"

	"github.com/r3labs/sse/v2"
	"go.uber.org/zap"
)

type Config struct {
	UseSSE     bool
	Endpoint   string
	SSEPath    string
	MCPPath    string
	Logger     *zap.SugaredLogger
	AuthConfig *AuthConfig
}

type MCPEngine struct {
	endpoint   string
	inputFile  *os.File
	outputFile *os.File
	useSse     bool
	sseClient  sseClient
	mcpPath    string
	httpClient *http.Client
	auth       *AuthManager
	logger     *zap.SugaredLogger
}

func New(cfg Config) (*MCPEngine, error) {
	var sseClient sseClient
	if cfg.UseSSE {
		sseClient = sse.NewClient(fmt.Sprintf("%s%s", cfg.Endpoint, cfg.SSEPath))
	}
	return &MCPEngine{
		endpoint:   cfg.Endpoint,
		inputFile:  os.Stdin,
		outputFile: os.Stdout,
		useSse:     cfg.UseSSE,
		sseClient:  sseClient,
		mcpPath:    cfg.MCPPath,
		httpClient: &http.Client{},
		logger:     cfg.Logger,
		auth:       NewAuthManager(cfg.AuthConfig, cfg.Logger.With("svc", "auth")),
	}, nil
}

func (mcp *MCPEngine) Start(ctx context.Context) {
	// STDIN -> HTTP POST
	stdinToPost := make(chan string, 1_000)
	// HTTP SSE -> path for HTTP Posts
	postPathChan := make(chan string, 1)
	// These all get written to STDOUT line by line
	stdoutChan := make(chan string, 1_000)

	workers := map[string]worker{
		"file-reader": NewFileReader(mcp.inputFile, stdinToPost, mcp.logger.With("worker", "file-reader")),
		"http-post":   NewHTTPPostSender(mcp.httpClient, mcp.endpoint, postPathChan, stdinToPost, stdoutChan, mcp.auth, mcp.logger.With("worker", "http-post")),
		"stdout":      NewOutputProxy(mcp.outputFile, stdoutChan, mcp.logger.With("worker", "stdout")),
	}

	if mcp.useSse {
		workers["sse"] = NewSSEWorker(mcp.sseClient, postPathChan, stdoutChan, mcp.logger.With("worker", "sse"))
	} else {
		postPathChan <- mcp.mcpPath
	}

	mcp.logger.Info("Running MCPEngine")
	mcp.runWorkersAndWait(ctx, workers, mcp.logger)
	mcp.logger.Info("MCPEngine Exited")
}

type worker interface {
	Run(ctx context.Context, cancel context.CancelFunc) error
}

func (mcp *MCPEngine) runWorkersAndWait(ctx context.Context, workers map[string]worker, logger *zap.SugaredLogger) {
	ctx, cancel := context.WithCancel(ctx)
	defer cancel()

	var wg sync.WaitGroup
	wg.Add(len(workers))
	for name, worker := range workers {
		constWorker := worker
		go func() {
			defer wg.Done()
			logger.Debugw("Starting worker", "worker-name", name)
			err := constWorker.Run(ctx, cancel)
			mcp.logger.Infow("Worker exited with error", "worker-name", name, "err", err)
		}()
	}
	wg.Wait()
}

// AuthError holds error details extracted from a 401 or 403 response.
type AuthError struct {
	WWWAuthenticate string `json:"www_authenticate"`
}

// FileReader reads lines from a file and sends them to an output message channel.
type FileReader struct {
	file       *os.File
	outputChan chan string
	logger     *zap.SugaredLogger
}

// NewFileReader constructs a new FileReader.
func NewFileReader(file *os.File, outputChan chan string, logger *zap.SugaredLogger) *FileReader {
	return &FileReader{
		file:       file,
		outputChan: outputChan,
		logger:     logger,
	}
}

// Run reads the file line by line and sends each line to the output channel.
// It stops when the file is exhausted or when the context is cancelled.
// The output channel is closed before returning.
func (fr *FileReader) Run(ctx context.Context, cancel context.CancelFunc) error {
	fr.logger.Debug("Starting to read file")
	defer close(fr.outputChan)
	scanner := bufio.NewScanner(fr.file)
	for scanner.Scan() {
		// Respect context cancellation.
		select {
		case <-ctx.Done():
			fr.logger.Info("FileReader canceled")
			return ctx.Err()
		default:
		}
		line := scanner.Text()
		fr.logger.Debugw("Read line", "line", line)
		fr.outputChan <- line
	}
	if err := scanner.Err(); err != nil {
		fr.logger.Errorf("Error reading file: %v", err)
		return err
	}
	return io.EOF
}

// HTTPPostSender waits for an endpoint from its endpoint channel and then posts
// messages received on its input channel to that endpoint via an HTTP client.
// It supports a global access token that can be updated concurrently.
type HTTPPostSender struct {
	client       *http.Client
	host         string
	endpointChan chan string // Supplies the endpoint (host URL) as a string.
	inputChan    chan string // Messages to send.
	outputChan   chan string // Messages that go directly to user in case of auth error.
	auth         *AuthManager
	logger       *zap.SugaredLogger
}

// NewHTTPPostSender constructs a new HTTPPostSender.
func NewHTTPPostSender(
	client *http.Client, host string,
	endpointChan, inputChan, outputChan chan string,
	auth *AuthManager,
	logger *zap.SugaredLogger,
) *HTTPPostSender {
	return &HTTPPostSender{
		client:       client,
		host:         host,
		endpointChan: endpointChan,
		inputChan:    inputChan,
		outputChan:   outputChan,
		logger:       logger,
		auth:         auth,
	}
}

// Run waits to receive an endpoint from endpointChan and then continuously reads messages
// from inputChan, posting each to the resolved endpoint. It stops when inputChan is closed
// or when the context is cancelled.
func (hs *HTTPPostSender) Run(ctx context.Context, cancel context.CancelFunc) error {
	hs.logger.Debug("Starting HTTPPostSender")
	hs.logger.Debug("Waiting for POST path")
	var endpointPath string
	select {
	case <-ctx.Done():
		hs.logger.Info("HTTPPostSender canceled before receiving endpoint")
		return ctx.Err()
	case endpointPath = <-hs.endpointChan:
	}
	parsedURL, err := url.Parse(fmt.Sprintf("%s%s", hs.host, endpointPath))
	if err != nil {
		hs.logger.Errorf("Invalid endpoint URL: %v", err)
		return err
	}

	hs.logger.Debugw("Received endpoint starting to listen to messages", "post-path", parsedURL)
	// Process messages.
	for {
		select {
		case <-ctx.Done():
			hs.logger.Info("HTTPPostSender canceled")
			return ctx.Err()
		case msg, ok := <-hs.inputChan:
			hs.logger.Debugw("Received message, sending over POST", "msg", msg)
			if !ok {
				hs.logger.Info("Input channel closed, terminating HTTPPostSender")
				return nil
			}
			req, err := http.NewRequestWithContext(ctx, http.MethodPost, parsedURL.String(), strings.NewReader(msg))
			if err != nil {
				hs.logger.Errorf("Failed to create request: %v", err)
				continue
			}
			req.Header.Set("Content-Type", "application/json")
			// Add access token header if available.
			if token := hs.auth.GetAccessToken(); token != "" {
				hs.logger.Debug("Setting auth token")
				req.Header.Set("Authorization", "Bearer "+token)
			}
			resp, err := hs.client.Do(req)
			if err != nil {
				hs.logger.Errorf("Failed to post message: %v", err)
				continue
			}
			// Handle response status.
			switch resp.StatusCode {
			// In the case of a 200, the response is directly in the body.
			case http.StatusOK:
				body, err := io.ReadAll(resp.Body)
				if err != nil {
					fmt.Println("Error reading body:", err)
					break
				}
				bodyString := string(body)
				hs.logger.Debugf("Response received: %s", bodyString)
				hs.outputChan <- bodyString
			case http.StatusAccepted:
				hs.logger.Debugf("Message accepted: %s", msg)
			case http.StatusUnauthorized, http.StatusForbidden:
				hs.logger.Debug("Unauthorized message")
				id := getMessageID(msg, hs.logger)
				authURL, wait, err := hs.auth.HandleAuthChallenge(ctx, resp)
				if err != nil {
					hs.logger.Errorw("Failed to create auth challenge", "err", err)
					continue
				}
				go func() {
					hs.logger.Info("Waiting for auth callback server")
					wait()
					hs.logger.Info("Auth callback server closed")
				}()
				authErr := createAuthError(id, authURL)
				authErrData, err := json.Marshal(authErr)
				if err != nil {
					hs.logger.Errorf("Failed to marshal auth error: %v", err)
				}
				authErrStr := string(authErrData)
				hs.logger.Debug("Sending auth error to output", "auth-err", authErrStr)
				hs.outputChan <- authErrStr
			default:
				hs.logger.Warnf("Unexpected response status: %d", resp.StatusCode)
			}
			io.Copy(io.Discard, resp.Body)
			resp.Body.Close()
		}
	}
}

// getMessageID takes a JSON string, parses it, and returns the top-level 'id' field as an int.
// If the 'id' field is not present or cannot be converted to an int, it returns -1.
func getMessageID(jsonStr string, logger *zap.SugaredLogger) int {
	var data map[string]interface{}
	if err := json.Unmarshal([]byte(jsonStr), &data); err != nil {
		logger.Errorf("Error parsing JSON: ", err)
		return -1
	}

	if idVal, exists := data["id"]; exists {
		switch v := idVal.(type) {
		case float64:
			// Use math.Round to round the float value to the nearest integer.
			return int(math.Round(v))
		case string:
			// Try converting the string to a float64 then round it.
			if f, err := strconv.ParseFloat(v, 64); err == nil {
				return int(math.Round(f))
			}
		}
	}
	// Returning -1 is a common sentinel value when a valid id isn't found,
	// as long as it's clear to callers that a negative id indicates an error or absence.
	return -1
}

type JSONRPCResponse struct {
	Result  Result `json:"result"`
	JSONRPC string `json:"jsonrpc"`
	ID      int    `json:"id"`
}

type Result struct {
	Content []ContentItem `json:"content"`
	IsError bool          `json:"isError"`
}

type ContentItem struct {
	Type string `json:"type"`
	Text string `json:"text"`
}

// CreateAuthError creates a JSONRPCResponse with default values,
// only requiring an id and an error message.
func createAuthError(id int, url string) JSONRPCResponse {
	return JSONRPCResponse{
		Result: Result{
			Content: []ContentItem{
				{
					Type: "text",
					Text: fmt.Sprintf("This user is currently unauthorized to perform this operation. Please tell them to go to %s to authenticate. Then come back and tell you to try again.", url),
				},
			},
			IsError: true,
		},
		JSONRPC: "2.0",
		ID:      id,
	}
}

// OutputProxy reads messages from an input channel and writes them to a file.
type OutputProxy struct {
	file      *os.File
	inputChan chan string
	logger    *zap.SugaredLogger
}

// NewOutputProxy creates a new OutputProxy with the provided file, channel, and logger.
func NewOutputProxy(file *os.File, inputChan chan string, logger *zap.SugaredLogger) *OutputProxy {
	return &OutputProxy{
		file:      file,
		inputChan: inputChan,
		logger:    logger,
	}
}

// Run continuously reads from the input channel and writes each message to the file,
// appending a newline after each message. It returns when the channel is closed or
// the context is canceled.
func (op *OutputProxy) Run(ctx context.Context, cancel context.CancelFunc) error {
	writer := bufio.NewWriter(op.file)
	defer writer.Flush()

	op.logger.Debug("Running output proxy")
	for {
		select {
		case <-ctx.Done():
			op.logger.Info("OutputProxy run canceled")
			return ctx.Err()
		case msg, ok := <-op.inputChan:
			if !ok {
				op.logger.Info("Input channel closed, terminating OutputProxy")
				return nil
			}
			// Write the message with a newline.
			if _, err := writer.WriteString(msg + "\n"); err != nil {
				op.logger.Errorf("Failed to write message: %v", err)
				return err
			}
			// Flush after each message.
			if err := writer.Flush(); err != nil {
				op.logger.Errorf("Failed to flush writer: %v", err)
				return err
			}
			op.logger.Debugw("Wrote message", "msg", msg)
		}
	}
}

// sseClient is implemented by *sse.Client and is used for dependency injection in tests.
type sseClient interface {
	SubscribeChan(stream string, msgs chan *sse.Event) error
}

// SSEWorker subscribes to an SSE stream, extracts an endpoint from the first relevant message,
// sends that endpoint to an endpoint channel, and then passes all received messages to an output channel.
type SSEWorker struct {
	client       sseClient
	endpointChan chan string // Channel to send the extracted endpoint.
	outputChan   chan string // Channel to send all received messages.
	logger       *zap.SugaredLogger
}

// NewSSEWorker constructs a new SSEWorker.
func NewSSEWorker(client sseClient, endpointChan, outputChan chan string, logger *zap.SugaredLogger) *SSEWorker {
	return &SSEWorker{
		client:       client,
		endpointChan: endpointChan,
		outputChan:   outputChan,
		logger:       logger,
	}
}

// Run subscribes to the "messages" SSE stream, waits for the first relevant endpoint message,
// sends that message to endpointChan, and then sends every SSE message to outputChan.
func (sw *SSEWorker) Run(ctx context.Context, cancel context.CancelFunc) error {
	msgChan := make(chan *sse.Event)
	go func() {
		sw.logger.Debug("Subscribing to messages channel")
		if err := sw.client.SubscribeChan("messages", msgChan); err != nil {
			sw.logger.Errorf("Failed to subscribe to SSE: %v", err)
		}
	}()
	// defer close(msgChan)

	endpointSent := false
	for {
		select {
		case <-ctx.Done():
			sw.logger.Info("SSEWorker canceled")
			return ctx.Err()
		case event, ok := <-msgChan:
			if !ok {
				sw.logger.Info("SSE event channel closed")
				return nil
			}
			msgStr := string(event.Data)
			sw.logger.Debugw("Received message", "msgStr", msgStr)
			// If this is the first relevant message, send it as the endpoint.
			if strings.HasPrefix(msgStr, "/messages/") || strings.Contains(msgStr, "session_id") {
				if endpointSent {
					sw.logger.Warn("Received second endpoint message, skipping", msgStr)
					continue
				}
				sw.logger.Debug("Sending endpoint: %s", msgStr)
				select {
				case sw.endpointChan <- msgStr:
					sw.logger.Infof("Sent endpoint: %s", msgStr)
					endpointSent = true
				case <-ctx.Done():
					sw.logger.Info("SSEWorker canceled while sending endpoint")
					return ctx.Err()
				}
			} else {
				select {
				case sw.outputChan <- msgStr:
					sw.logger.Debug("Message sent")
				case <-ctx.Done():
					sw.logger.Info("SSEWorker canceled")
					return ctx.Err()
				}
			}
		}
	}
}
