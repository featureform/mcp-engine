package testutil

import (
	"io"
	"os"
	"testing"
)

// BlockReader reads from the underlying Reader until EOF,
// then blocks forever on subsequent reads
type BlockReader struct {
	r          io.Reader
	reachedEOF bool
	blockChan  chan struct{}
}

// NewBlockReader creates a new reader that will block after EOF
func NewBlockReader(r io.Reader) *BlockReader {
	return &BlockReader{
		r:          r,
		reachedEOF: false,
		blockChan:  make(chan struct{}), // Unbuffered channel that's never closed
	}
}

func (r *BlockReader) Read(p []byte) (n int, err error) {
	if r.reachedEOF {
		// Block forever by trying to receive from a channel that will never send
		<-r.blockChan
		return 0, nil // This line is never reached
	}

	n, err = r.r.Read(p)
	if err == io.EOF {
		r.reachedEOF = true
		return n, nil // Return the data but suppress the EOF
	}
	return n, err
}

func CreateTempBlockReader(t *testing.T, content string) io.Reader {
	t.Helper()
	tmpFile, err := os.CreateTemp("", "mcpengine_input_*")
	if err != nil {
		t.Fatalf("Failed to create temporary file: %v", err)
	}
	t.Cleanup(func() {
		err := os.Remove(tmpFile.Name())
		if err != nil {
			t.Errorf("Failed to remove temporary file: %v", err)
		}
	})

	if _, err := tmpFile.WriteString(content); err != nil {
		t.Fatalf("Failed to write to temporary file: %v", err)
	}
	if _, err := tmpFile.Seek(0, 0); err != nil {
		t.Fatalf("Failed to reset temporary file: %v", err)
	}
	return NewBlockReader(tmpFile)
}
