package mcpengine

import (
	"context"
	"fmt"
	"testing"
	"time"

	"github.com/r3labs/sse/v2"
	"go.uber.org/zap"
)

// ===== SSE Worker Tests =====

// fakeSSEClient implements the sseClient interface for testing
type fakeSSEClient struct {
	Events       chan *sse.Event
	IsSubscribed chan struct{}
	SubscribeErr error
}

func (fc *fakeSSEClient) SubscribeChan(stream string, msgChan chan *sse.Event) error {
	if fc.SubscribeErr != nil {
		return fc.SubscribeErr
	}
	if stream != "messages" {
		return fmt.Errorf("unexpected stream: %s", stream)
	}
	fc.Events = msgChan
	close(fc.IsSubscribed)
	return nil
}

func TestSSEWorker_PassesEndpointAndMessages(t *testing.T) {
	// Create a fake SSE client
	fakeClient := &fakeSSEClient{
		IsSubscribed: make(chan struct{}),
	}

	endpointChan := make(chan string, 1)
	outputChan := make(chan string, 10)
	logger := zap.NewNop().Sugar()

	worker := NewSSEWorker(fakeClient, endpointChan, outputChan, logger)

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	go worker.Run(ctx, cancel)
	<-fakeClient.IsSubscribed // Wait for subscription

	// Simulate sending SSE events
	// First, send an "endpoint" event
	endpointMsg := "/messages/endpoint?session_id=abc"
	fakeClient.Events <- &sse.Event{Data: []byte(endpointMsg)}

	// Then send regular messages
	message1 := "Hello SSE"
	message2 := "Another message"
	fakeClient.Events <- &sse.Event{Data: []byte(message1)}
	fakeClient.Events <- &sse.Event{Data: []byte(message2)}

	// Allow time for processing
	time.Sleep(200 * time.Millisecond)

	// Check endpoint
	select {
	case ep := <-endpointChan:
		if ep != endpointMsg {
			t.Errorf("Expected endpoint %q, got %q", endpointMsg, ep)
		}
	default:
		t.Error("Expected an endpoint message but got none")
	}

	// Check regular messages
	var received []string
	for i := 0; i < 2; i++ {
		select {
		case msg := <-outputChan:
			received = append(received, msg)
		case <-time.After(200 * time.Millisecond):
			t.Fatal("Timeout waiting for messages")
		}
	}

	expected := []string{message1, message2}
	for i, exp := range expected {
		if received[i] != exp {
			t.Errorf("Message %d: expected %q, got %q", i, exp, received[i])
		}
	}
}

func TestSSEWorker_EndpointDetection(t *testing.T) {
	// Test various endpoint detection patterns
	testCases := []struct {
		name             string
		message          string
		shouldBeEndpoint bool
	}{
		{
			name:             "messages path format",
			message:          "/messages/12345",
			shouldBeEndpoint: true,
		},
		{
			name:             "session_id format",
			message:          "something?session_id=abc",
			shouldBeEndpoint: true,
		},
		{
			name:             "regular message",
			message:          "This is a regular message",
			shouldBeEndpoint: false,
		},
		{
			name:             "contains but not starts with /messages/",
			message:          "path is /messages/12345",
			shouldBeEndpoint: false,
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			fakeClient := &fakeSSEClient{
				IsSubscribed: make(chan struct{}),
			}

			endpointChan := make(chan string, 1)
			outputChan := make(chan string, 1)
			logger := zap.NewNop().Sugar()

			worker := NewSSEWorker(fakeClient, endpointChan, outputChan, logger)

			ctx, cancel := context.WithTimeout(context.Background(), 1*time.Second)
			defer cancel()

			go worker.Run(ctx, cancel)
			<-fakeClient.IsSubscribed

			// Send the test message
			fakeClient.Events <- &sse.Event{Data: []byte(tc.message)}

			// Allow time for processing
			time.Sleep(100 * time.Millisecond)

			if tc.shouldBeEndpoint {
				// Should be in endpoint channel
				select {
				case ep := <-endpointChan:
					if ep != tc.message {
						t.Errorf("Expected endpoint %q, got %q", tc.message, ep)
					}
				default:
					t.Error("Expected an endpoint message but got none")
				}

				// Should not be in output channel
				select {
				case msg := <-outputChan:
					t.Errorf("Unexpected message in output channel: %q", msg)
				default:
					// Expected - nothing in output channel
				}
			} else {
				// Should not be in endpoint channel
				select {
				case ep := <-endpointChan:
					t.Errorf("Unexpected endpoint: %q", ep)
				default:
					// Expected - nothing in endpoint channel
				}

				// Should be in output channel
				select {
				case msg := <-outputChan:
					if msg != tc.message {
						t.Errorf("Expected message %q, got %q", tc.message, msg)
					}
				default:
					t.Error("Expected a message in output channel but got none")
				}
			}
		})
	}
}

func TestSSEWorker_SkipsSubsequentEndpoints(t *testing.T) {
	// Test that worker only forwards the first endpoint message
	fakeClient := &fakeSSEClient{
		IsSubscribed: make(chan struct{}),
	}

	endpointChan := make(chan string, 1)
	outputChan := make(chan string, 10)
	logger := zap.NewNop().Sugar()

	worker := NewSSEWorker(fakeClient, endpointChan, outputChan, logger)

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	go worker.Run(ctx, cancel)
	<-fakeClient.IsSubscribed

	// Send two endpoint messages - only the first should be forwarded
	endpoint1 := "/messages/endpoint1?session_id=abc"
	endpoint2 := "/messages/endpoint2?session_id=def"
	regularMsg := "Regular message"

	fakeClient.Events <- &sse.Event{Data: []byte(endpoint1)}
	fakeClient.Events <- &sse.Event{Data: []byte(endpoint2)}
	fakeClient.Events <- &sse.Event{Data: []byte(regularMsg)}

	// Allow time for processing
	time.Sleep(200 * time.Millisecond)

	// Check that only the first endpoint was sent
	select {
	case ep := <-endpointChan:
		if ep != endpoint1 {
			t.Errorf("Expected endpoint %q, got %q", endpoint1, ep)
		}
	default:
		t.Error("Expected an endpoint message but got none")
	}

	// Verify the endpoint channel is empty (second endpoint was not forwarded)
	select {
	case ep := <-endpointChan:
		t.Errorf("Unexpected second endpoint: %q", ep)
	default:
		// Expected, channel should be empty
	}

	// The second endpoint message should have been skipped
	// The regular message should be in the output channel
	var outputMessages []string
	for i := 0; i < 2; i++ {
		select {
		case msg := <-outputChan:
			outputMessages = append(outputMessages, msg)
		case <-time.After(100 * time.Millisecond):
			// No more messages
			break
		}
	}

	// Both endpoint messages should appear in the output
	// (even though only the first was sent through the endpoint channel)
	if len(outputMessages) != 1 {
		t.Errorf("Expected 1 output message, got %d: %v", len(outputMessages), outputMessages)
	}
}

func TestSSEWorker_Cancellation(t *testing.T) {
	// Test that the worker respects context cancellation
	fakeClient := &fakeSSEClient{
		IsSubscribed: make(chan struct{}),
	}

	endpointChan := make(chan string)
	outputChan := make(chan string)
	logger := zap.NewNop().Sugar()

	worker := NewSSEWorker(fakeClient, endpointChan, outputChan, logger)

	// Create a context and cancel it immediately
	ctx, cancel := context.WithCancel(context.Background())

	// Run the worker in a goroutine and capture the result
	errCh := make(chan error, 1)
	go func() {
		errCh <- worker.Run(ctx, cancel)
	}()

	// Wait for subscription
	<-fakeClient.IsSubscribed

	// Cancel the context
	cancel()

	// Check that the worker exits with the correct error
	select {
	case err := <-errCh:
		if err != context.Canceled {
			t.Errorf("Expected context.Canceled error, got: %v", err)
		}
	case <-time.After(500 * time.Millisecond):
		t.Fatal("SSEWorker did not respect context cancellation")
	}
}

func TestSSEWorker_EventChannelClosure(t *testing.T) {
	// Test that the worker handles the SSE event channel being closed
	fakeClient := &fakeSSEClient{
		IsSubscribed: make(chan struct{}),
	}

	endpointChan := make(chan string)
	outputChan := make(chan string)
	logger := zap.NewNop().Sugar()

	worker := NewSSEWorker(fakeClient, endpointChan, outputChan, logger)

	ctx, cancel := context.WithCancel(context.Background())

	// Run the worker in a goroutine and capture the result
	errCh := make(chan error, 1)
	go func() {
		errCh <- worker.Run(ctx, cancel)
	}()

	// Wait for subscription
	<-fakeClient.IsSubscribed

	// Close the event channel to simulate the SSE connection closing
	close(fakeClient.Events)

	// Check that the worker exits without error
	select {
	case err := <-errCh:
		if err != nil {
			t.Errorf("Expected nil error, got: %v", err)
		}
	case <-time.After(500 * time.Millisecond):
		t.Fatal("SSEWorker did not exit after event channel closed")
	}
}

func TestSSEWorker_SubscribeError(t *testing.T) {
	// Test handling of subscription errors
	subscribeErr := fmt.Errorf("subscription failed")
	fakeClient := &fakeSSEClient{
		IsSubscribed: make(chan struct{}),
		SubscribeErr: subscribeErr,
	}

	endpointChan := make(chan string)
	outputChan := make(chan string)
	logger := zap.NewNop().Sugar()

	worker := NewSSEWorker(fakeClient, endpointChan, outputChan, logger)

	// The worker should continue running even if subscription fails,
	// so we need to cancel the context to end the test
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()

	err := worker.Run(ctx, cancel)

	// Should return context cancellation error, not subscription error
	if err != context.DeadlineExceeded {
		t.Errorf("Expected DeadlineExceeded error, got: %v", err)
	}
}
