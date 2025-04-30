package mcpengine

import (
	"bytes"
	"context"
	"io"
	"os"
	"strings"
	"testing"
	"time"

	"go.uber.org/zap"
)

// createTempFile is a helper that creates and returns a temporary file containing content.
func createTempFile(t *testing.T, name, content string) *os.File {
	t.Helper()
	tmpFile, err := os.CreateTemp("", name)
	if err != nil {
		t.Fatalf("Failed to create temporary file: %v", err)
	}
	if _, err := tmpFile.WriteString(content); err != nil {
		t.Fatalf("Failed to write to temporary file: %v", err)
	}
	if _, err := tmpFile.Seek(0, 0); err != nil {
		t.Fatalf("Failed to reset temporary file: %v", err)
	}
	return tmpFile
}

// ===== FileReader Tests =====

func TestFileReader_ReadsLines(t *testing.T) {
	content := "line1\nline2\nline3\n"
	tmpFile := createTempFile(t, "filereader_readlines", content)
	defer os.Remove(tmpFile.Name())
	defer tmpFile.Close()

	outputChan := make(chan string, 10)
	logger := zap.NewNop().Sugar()

	fr := NewFileReader(tmpFile, outputChan, logger)

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	go fr.Run(ctx, cancel)

	var lines []string
	for line := range outputChan {
		lines = append(lines, line)
	}
	expected := []string{"line1", "line2", "line3"}
	if len(lines) != len(expected) {
		t.Fatalf("expected %d lines, got %d", len(expected), len(lines))
	}
	for i, l := range expected {
		if lines[i] != l {
			t.Errorf("line %d: expected %q, got %q", i, l, lines[i])
		}
	}
}

func TestFileReader_EmptyFile(t *testing.T) {
	// Test with an empty file
	tmpFile := createTempFile(t, "filereader_empty", "")
	defer os.Remove(tmpFile.Name())
	defer tmpFile.Close()

	outputChan := make(chan string, 10)
	logger := zap.NewNop().Sugar()

	fr := NewFileReader(tmpFile, outputChan, logger)

	ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()

	err := fr.Run(ctx, cancel)
	if err != io.EOF {
		t.Errorf("Unexpected error: %v", err)
	}

	// Channel should be closed with no messages
	count := 0
	for range outputChan {
		count++
	}

	if count != 0 {
		t.Errorf("Expected 0 lines from empty file, got %d", count)
	}
}

func TestFileReader_Cancellation(t *testing.T) {
	// Create a file with many lines.
	var buf bytes.Buffer
	for i := 0; i < 1000; i++ {
		buf.WriteString("line\n")
	}
	tmpFile := createTempFile(t, "filereader_cancel", buf.String())
	defer os.Remove(tmpFile.Name())
	defer tmpFile.Close()

	outputChan := make(chan string, 1000)
	logger := zap.NewNop().Sugar()
	fr := NewFileReader(tmpFile, outputChan, logger)

	ctx, cancel := context.WithCancel(context.Background())
	cancel() // cancel immediately

	go fr.Run(ctx, cancel)

	// Expect the output channel to close quickly.
	select {
	case _, ok := <-outputChan:
		if ok {
			// It's possible some lines were sent before cancellation.
		}
	case <-time.After(500 * time.Millisecond):
		t.Error("FileReader did not terminate after cancellation")
	}
}

func TestFileReader_FileError(t *testing.T) {
	// Create a file and then close it to simulate an I/O error
	tmpFile := createTempFile(t, "filereader_error", "data")
	tmpName := tmpFile.Name()
	tmpFile.Close()    // Close immediately to cause scanner errors
	os.Remove(tmpName) // Remove file to ensure error

	outputChan := make(chan string, 10)
	logger := zap.NewNop().Sugar()

	// Open non-existent file to cause error
	badFile, _ := os.Open(tmpName)
	fr := NewFileReader(badFile, outputChan, logger)

	ctx, cancel := context.WithCancel(context.Background())
	err := fr.Run(ctx, cancel)

	// Should return an error
	if err == nil {
		t.Error("Expected an error when reading from a bad file, got nil")
	}
}

// ===== OutputProxy Tests =====

func TestOutputProxy_WritesMessages(t *testing.T) {
	// Create a temporary file
	tmpFile := createTempFile(t, "outputproxy", "")
	defer os.Remove(tmpFile.Name())
	defer tmpFile.Close()

	// Prepare messages
	messages := []string{"hello", "world", "test"}
	inputChan := make(chan string, len(messages))
	for _, msg := range messages {
		inputChan <- msg
	}
	close(inputChan)

	logger := zap.NewNop().Sugar()
	proxy := NewOutputProxy(tmpFile, inputChan, logger)

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := proxy.Run(ctx, cancel); err != nil {
		t.Fatalf("OutputProxy Run returned error: %v", err)
	}

	// Read the file content and verify it
	data, err := os.ReadFile(tmpFile.Name())
	if err != nil {
		t.Fatalf("Failed to read temp file: %v", err)
	}
	expected := strings.Join(messages, "\n") + "\n"
	if got := string(data); got != expected {
		t.Errorf("Unexpected file content:\ngot: %q\nwant: %q", got, expected)
	}
}

func TestOutputProxy_WriteFails(t *testing.T) {
	// Create a file and then close it to cause write errors
	tmpFile := createTempFile(t, "outputproxy_error", "")
	tmpFile.Close() // Close file to cause write errors

	inputChan := make(chan string, 1)
	logger := zap.NewNop().Sugar()

	// Send a message
	inputChan <- "test message"

	// Try to use the closed file
	proxy := NewOutputProxy(tmpFile, inputChan, logger)

	ctx, cancel := context.WithCancel(context.Background())
	err := proxy.Run(ctx, cancel)

	// Should return an error
	if err == nil {
		t.Error("Expected error when writing to closed file, got nil")
	}
}

func TestOutputProxy_Cancellation(t *testing.T) {
	// Create a temporary file
	tmpFile := createTempFile(t, "outputproxy_cancel", "")
	defer os.Remove(tmpFile.Name())
	defer tmpFile.Close()

	// Create an input channel that never closes
	inputChan := make(chan string)
	logger := zap.NewNop().Sugar()
	proxy := NewOutputProxy(tmpFile, inputChan, logger)

	// Create a context that is canceled after a short delay
	ctx, cancel := context.WithTimeout(context.Background(), 100*time.Millisecond)
	defer cancel()

	// Run the proxy; we expect it to return a cancellation error
	err := proxy.Run(ctx, cancel)
	if err == nil {
		t.Error("Expected error due to context cancellation, got nil")
	}
}

func TestOutputProxy_ChannelClosedWhileBlocked(t *testing.T) {
	// Test behavior when the channel is closed while the proxy is blocked waiting for a message
	tmpFile := createTempFile(t, "outputproxy_blocked", "")
	defer os.Remove(tmpFile.Name())
	defer tmpFile.Close()

	inputChan := make(chan string)
	logger := zap.NewNop().Sugar()
	proxy := NewOutputProxy(tmpFile, inputChan, logger)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Run the proxy in a goroutine
	errCh := make(chan error, 1)
	go func() {
		errCh <- proxy.Run(ctx, cancel)
	}()

	// Allow time for proxy to start and block on channel
	time.Sleep(100 * time.Millisecond)

	// Close the channel
	close(inputChan)

	// Check that the proxy exits gracefully
	select {
	case err := <-errCh:
		if err != nil {
			t.Errorf("Unexpected error: %v", err)
		}
	case <-time.After(500 * time.Millisecond):
		t.Error("OutputProxy did not terminate after channel was closed")
	}
}

func TestOutputProxy_FlushAfterEachMessage(t *testing.T) {
	// Test that messages are flushed to the file immediately, not just when the proxy exits
	tmpFile := createTempFile(t, "outputproxy_flush", "")
	defer os.Remove(tmpFile.Name())
	defer tmpFile.Close()

	inputChan := make(chan string, 3)
	logger := zap.NewNop().Sugar()
	proxy := NewOutputProxy(tmpFile, inputChan, logger)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Start the proxy in a goroutine
	go proxy.Run(ctx, cancel)

	// Send one message
	inputChan <- "first message"

	// Allow time for message to be processed
	time.Sleep(100 * time.Millisecond)

	// Check that the message was written to the file
	data, err := os.ReadFile(tmpFile.Name())
	if err != nil {
		t.Fatalf("Failed to read temp file: %v", err)
	}
	if got := string(data); !strings.Contains(got, "first message") {
		t.Errorf("Expected file to contain 'first message', got: %q", got)
	}

	// Send another message
	inputChan <- "second message"

	// Allow time for message to be processed
	time.Sleep(100 * time.Millisecond)

	// Check that both messages are in the file
	data, err = os.ReadFile(tmpFile.Name())
	if err != nil {
		t.Fatalf("Failed to read temp file: %v", err)
	}
	if got := string(data); !strings.Contains(got, "second message") {
		t.Errorf("Expected file to contain 'second message', got: %q", got)
	}
}
