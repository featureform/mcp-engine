package mcpengine

import (
	"encoding/json"
	"reflect"
	"testing"

	"go.uber.org/zap"
)

// TestGetMessageID tests the message ID extraction function
func TestGetMessageID(t *testing.T) {
	logger := zap.NewNop().Sugar()

	testCases := []struct {
		name     string
		jsonStr  string
		expected int
	}{
		{
			name:     "integer id",
			jsonStr:  `{"id": 123, "method": "test"}`,
			expected: 123,
		},
		{
			name:     "string id",
			jsonStr:  `{"id": "456", "method": "test"}`,
			expected: 456,
		},
		{
			name:     "float id",
			jsonStr:  `{"id": 789.0, "method": "test"}`,
			expected: 789,
		},
		{
			name:     "missing id",
			jsonStr:  `{"method": "test"}`,
			expected: -1,
		},
		{
			name:     "invalid JSON",
			jsonStr:  `{not valid json`,
			expected: -1,
		},
		{
			name:     "non-numeric string id",
			jsonStr:  `{"id": "abc", "method": "test"}`,
			expected: -1,
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			id := getMessageID(tc.jsonStr, logger)
			if id != tc.expected {
				t.Errorf("Expected ID %d, got %d", tc.expected, id)
			}
		})
	}
}

// TestCreateAuthError tests the auth error creation function
func TestCreateAuthError(t *testing.T) {
	testCases := []struct {
		name     string
		id       int
		url      string
		expected JSONRPCResponse
	}{
		{
			name: "simple auth error",
			id:   123,
			url:  "https://auth.example.com",
			expected: JSONRPCResponse{
				Result: Result{
					Content: []ContentItem{
						{
							Type: "text",
							Text: "This user is currently unauthorized to perform this operation. Please tell them to go to https://auth.example.com to authenticate. Then come back and tell you to try again.",
						},
					},
					IsError: true,
				},
				JSONRPC: "2.0",
				ID:      123,
			},
		},
		{
			name: "negative id",
			id:   -1,
			url:  "https://auth.example.com",
			expected: JSONRPCResponse{
				Result: Result{
					Content: []ContentItem{
						{
							Type: "text",
							Text: "This user is currently unauthorized to perform this operation. Please tell them to go to https://auth.example.com to authenticate. Then come back and tell you to try again.",
						},
					},
					IsError: true,
				},
				JSONRPC: "2.0",
				ID:      -1,
			},
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			result := createAuthError(tc.id, tc.url)
			if !reflect.DeepEqual(result, tc.expected) {
				t.Errorf("Expected %+v, got %+v", tc.expected, result)
			}

			// Also check JSON serialization for proper integration with API response
			jsonData, err := json.Marshal(result)
			if err != nil {
				t.Fatalf("JSON marshaling failed: %v", err)
			}

			var unmarshaled JSONRPCResponse
			if err := json.Unmarshal(jsonData, &unmarshaled); err != nil {
				t.Fatalf("JSON unmarshaling failed: %v", err)
			}

			if !reflect.DeepEqual(unmarshaled, tc.expected) {
				t.Errorf("JSON roundtrip failed, expected %+v, got %+v", tc.expected, unmarshaled)
			}
		})
	}
}

// TestMCPEngineConfig tests the configuration behavior
func TestMCPEngineConfig(t *testing.T) {
	logger := zap.NewNop().Sugar()

	testCases := []struct {
		name           string
		config         Config
		expectEndpoint string
		expectError    bool
	}{
		{
			name: "valid config",
			config: Config{
				Endpoint:   "https://example.com",
				SSEPath:    "/sse",
				Logger:     logger,
				AuthConfig: &AuthConfig{},
			},
			expectEndpoint: "https://example.com",
			expectError:    false,
		},
		{
			name: "empty SSE path",
			config: Config{
				Endpoint:   "https://example.com",
				SSEPath:    "",
				Logger:     logger,
				AuthConfig: nil,
			},
			expectEndpoint: "https://example.com",
			expectError:    false,
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			engine, err := New(tc.config)

			if tc.expectError {
				if err == nil {
					t.Error("Expected error, got nil")
				}
			} else {
				if err != nil {
					t.Errorf("Unexpected error: %v", err)
				}

				if engine.endpoint != tc.expectEndpoint {
					t.Errorf("Expected endpoint %s, got %s", tc.expectEndpoint, engine.endpoint)
				}

				if engine.inputFile == nil {
					t.Error("inputFile is nil")
				}

				if engine.outputFile == nil {
					t.Error("outputFile is nil")
				}

				if engine.logger == nil {
					t.Error("logger is nil")
				}

				if engine.auth == nil {
					t.Error("auth is nil")
				}
			}
		})
	}
}
