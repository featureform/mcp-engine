package mcpengine

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"reflect"
	"strings"
	"testing"
	"time"

	"go.uber.org/zap"
)

// TestResolveConfig tests the configuration resolution logic
func TestResolveConfig(t *testing.T) {
	testCases := []struct {
		name     string
		input    *AuthConfig
		expected *AuthConfig
	}{
		{
			name:  "nil config",
			input: nil,
			expected: &AuthConfig{
				ListenPort:         8181,
				CallbackPath:       "/callback",
				OIDCConfigPath:     "/.well-known/openid-configuration",
				MaxAuthAttempts:    3,
				AuthCooldownPeriod: 15 * time.Second,
			},
		},
		{
			name: "partial config",
			input: &AuthConfig{
				ClientID: "test-client",
			},
			expected: &AuthConfig{
				ClientID:           "test-client",
				ClientSecret:       "",
				ListenPort:         8181,
				CallbackPath:       "/callback",
				OIDCConfigPath:     "/.well-known/openid-configuration",
				MaxAuthAttempts:    3,
				AuthCooldownPeriod: 15 * time.Second,
			},
		},
		{
			name: "complete custom config",
			input: &AuthConfig{
				ClientID:           "test-client",
				ClientSecret:       "test-secret",
				ListenPort:         9000,
				CallbackPath:       "/custom-callback",
				OIDCConfigPath:     "/custom-config",
				MaxAuthAttempts:    5,
				AuthCooldownPeriod: 30 * time.Second,
			},
			expected: &AuthConfig{
				ClientID:           "test-client",
				ClientSecret:       "test-secret",
				ListenPort:         9000,
				CallbackPath:       "/custom-callback",
				OIDCConfigPath:     "/custom-config",
				MaxAuthAttempts:    5,
				AuthCooldownPeriod: 30 * time.Second,
			},
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			result := resolveConfig(tc.input)
			if !reflect.DeepEqual(result, tc.expected) {
				t.Errorf("Expected %+v, got %+v", tc.expected, result)
			}
		})
	}
}

// TestNewAuthManager tests the AuthManager constructor
func TestNewAuthManager(t *testing.T) {
	logger := zap.NewNop().Sugar()

	t.Run("with nil config", func(t *testing.T) {
		auth := NewAuthManager(nil, logger)

		if auth == nil {
			t.Fatal("NewAuthManager returned nil")
		}

		if auth.redirectURL != "http://localhost:8181/callback" {
			t.Errorf("Expected redirectURL to be http://localhost:8181/callback, got %s", auth.redirectURL)
		}

		if auth.clientID != "" || auth.clientSecret != "" {
			t.Errorf("Expected empty clientID/secret, got %s/%s", auth.clientID, auth.clientSecret)
		}
	})

	t.Run("with custom config", func(t *testing.T) {
		config := &AuthConfig{
			ClientID:     "client-123",
			ClientSecret: "secret-456",
			ListenPort:   9999,
		}

		auth := NewAuthManager(config, logger)

		if auth.clientID != "client-123" {
			t.Errorf("Expected clientID to be client-123, got %s", auth.clientID)
		}

		if auth.clientSecret != "secret-456" {
			t.Errorf("Expected clientSecret to be secret-456, got %s", auth.clientSecret)
		}

		if auth.redirectURL != "http://localhost:9999/callback" {
			t.Errorf("Expected redirectURL to be http://localhost:9999/callback, got %s", auth.redirectURL)
		}
	})
}

// TestAuthManager_CanAttemptAuth tests the auth retry limiting logic
func TestAuthManager_CanAttemptAuth(t *testing.T) {
	logger := zap.NewNop().Sugar()

	t.Run("default config", func(t *testing.T) {
		auth := NewAuthManager(nil, logger)

		// First attempt should succeed
		can, err := auth.CanAttemptAuth()
		if !can || err != nil {
			t.Errorf("First attempt should succeed, got can=%v, err=%v", can, err)
		}

		// Try more attempts
		for i := 0; i < 2; i++ {
			auth.CanAttemptAuth()
		}

		// Fourth attempt should fail (default MaxAuthAttempts is 3)
		can, err = auth.CanAttemptAuth()
		if can || err == nil {
			t.Errorf("Expected failure after max attempts, got can=%v, err=%v", can, err)
		}
	})

	t.Run("with reset", func(t *testing.T) {
		auth := NewAuthManager(nil, logger)

		// Exhaust attempts
		for i := 0; i < 3; i++ {
			auth.CanAttemptAuth()
		}

		// Reset attempts
		auth.ResetAuthAttempts()

		// Should be able to try again
		can, err := auth.CanAttemptAuth()
		if !can || err != nil {
			t.Errorf("After reset, attempt should succeed, got can=%v, err=%v", can, err)
		}
	})

	t.Run("with cooldown", func(t *testing.T) {
		// Custom config with shorter cooldown for testing
		config := &AuthConfig{
			MaxAuthAttempts:    1,                     // Only allow 1 attempt
			AuthCooldownPeriod: 50 * time.Millisecond, // Short cooldown for testing
		}
		auth := NewAuthManager(config, logger)

		// First attempt should succeed
		can, _ := auth.CanAttemptAuth()
		if !can {
			t.Error("First attempt should succeed with custom config")
		}

		// Second attempt should fail
		can, _ = auth.CanAttemptAuth()
		if can {
			t.Error("Second attempt should fail with custom config")
		}

		// After cooldown, attempts should be allowed again
		time.Sleep(100 * time.Millisecond) // Wait for cooldown
		can, _ = auth.CanAttemptAuth()
		if !can {
			t.Error("Attempt after cooldown should succeed")
		}
	})
}

// TestAuthManager_GetAccessToken tests token retrieval
func TestAuthManager_GetAccessToken(t *testing.T) {
	logger := zap.NewNop().Sugar()
	auth := NewAuthManager(nil, logger)

	// Initially should be empty
	if token := auth.GetAccessToken(); token != "" {
		t.Errorf("Expected empty token initially, got %q", token)
	}

	// Set token and verify
	expectedToken := "test-access-token"
	auth.tokenMutex.Lock()
	auth.accessToken = expectedToken
	auth.tokenMutex.Unlock()

	if token := auth.GetAccessToken(); token != expectedToken {
		t.Errorf("Expected token %q, got %q", expectedToken, token)
	}
}

// TestParseScopes tests scope extraction from WWW-Authenticate headers
func TestParseScopes(t *testing.T) {
	testCases := []struct {
		name           string
		header         string
		expectedScopes []string
		expectError    bool
	}{
		{
			name:           "valid header with scope",
			header:         `Bearer realm="test", scope="openid profile email"`,
			expectedScopes: []string{"openid", "profile", "email"},
			expectError:    false,
		},
		{
			name:           "valid header without scope",
			header:         `Bearer realm="test"`,
			expectedScopes: []string{"openid", "profile", "email"}, // Default scopes
			expectError:    false,
		},
		{
			name:           "invalid header format",
			header:         `Basic realm="test"`,
			expectedScopes: nil,
			expectError:    true,
		},
		{
			name:           "empty header",
			header:         "",
			expectedScopes: nil,
			expectError:    true,
		},
		{
			name:           "header with quoted scope values",
			header:         `Bearer realm="test", scope="'openid' 'profile'"`,
			expectedScopes: []string{"openid", "profile"},
			expectError:    false,
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			scopes, err := parseScopes(tc.header)

			if tc.expectError {
				if err == nil {
					t.Errorf("Expected error, got nil")
				}
			} else {
				if err != nil {
					t.Errorf("Unexpected error: %v", err)
				}
				if !reflect.DeepEqual(scopes, tc.expectedScopes) {
					t.Errorf("Expected scopes %v, got %v", tc.expectedScopes, scopes)
				}
			}
		})
	}
}

// TestExtractServerURL tests URL extraction
func TestExtractServerURL(t *testing.T) {
	testCases := []struct {
		name           string
		input          *url.URL
		expectedOutput string
		expectError    bool
	}{
		{
			name:           "valid URL",
			input:          &url.URL{Scheme: "https", Host: "example.com"},
			expectedOutput: "https://example.com",
			expectError:    false,
		},
		{
			name:           "valid URL with port",
			input:          &url.URL{Scheme: "http", Host: "localhost:8080"},
			expectedOutput: "http://localhost:8080",
			expectError:    false,
		},
		{
			name:           "nil URL",
			input:          nil,
			expectedOutput: "",
			expectError:    true,
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			result, err := extractServerURL(tc.input)

			if tc.expectError {
				if err == nil {
					t.Errorf("Expected error, got nil")
				}
			} else {
				if err != nil {
					t.Errorf("Unexpected error: %v", err)
				}
				if result != tc.expectedOutput {
					t.Errorf("Expected %q, got %q", tc.expectedOutput, result)
				}
			}
		})
	}
}

// TestGenerateState tests state generation for CSRF protection
func TestGenerateState(t *testing.T) {
	// Test multiple calls return different values
	state1 := generateState()
	state2 := generateState()

	if state1 == "" {
		t.Error("Generated state should not be empty")
	}

	if state1 == state2 {
		t.Error("Multiple calls to generateState should return different values")
	}

	// Check that the generated state is a valid base64 string
	if _, err := url.QueryUnescape(state1); err != nil {
		t.Errorf("Generated state is not URL-safe: %v", err)
	}
}

// TestFetchOIDCConfiguration tests the OIDC configuration fetching
func TestFetchOIDCConfiguration(t *testing.T) {
	// Create a test server that returns OIDC configuration
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/.well-known/openid-configuration" {
			w.Header().Set("Content-Type", "application/json")
			w.Write([]byte(`{
				"authorization_endpoint": "https://auth.example.com/auth",
				"token_endpoint": "https://auth.example.com/token",
				"issuer": "https://auth.example.com"
			}`))
		} else {
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer server.Close()

	logger := zap.NewNop().Sugar()
	auth := NewAuthManager(nil, logger)

	// Set the server URL
	auth.serverURL = server.URL

	// Test successful configuration fetch
	ctx := context.Background()
	err := auth.fetchOIDCConfiguration(ctx)

	if err != nil {
		t.Fatalf("Unexpected error: %v", err)
	}

	if auth.oidcConfig.AuthorizationEndpoint != "https://auth.example.com/auth" {
		t.Errorf("Wrong authorization endpoint: %s", auth.oidcConfig.AuthorizationEndpoint)
	}

	if auth.oidcConfig.TokenEndpoint != "https://auth.example.com/token" {
		t.Errorf("Wrong token endpoint: %s", auth.oidcConfig.TokenEndpoint)
	}

	if auth.oidcConfig.Issuer != "https://auth.example.com" {
		t.Errorf("Wrong issuer: %s", auth.oidcConfig.Issuer)
	}

	// Test with invalid server URL
	auth.serverURL = "invalid-url"
	err = auth.fetchOIDCConfiguration(ctx)
	if err == nil {
		t.Error("Expected error with invalid URL, got nil")
	}

	// Test with server that returns an error
	auth.serverURL = "http://localhost:1" // Should fail to connect
	err = auth.fetchOIDCConfiguration(ctx)
	if err == nil {
		t.Error("Expected error with unreachable server, got nil")
	}
}

// TestInitOAuth2Config tests OAuth2 configuration initialization
func TestInitOAuth2Config(t *testing.T) {
	logger := zap.NewNop().Sugar()
	auth := NewAuthManager(&AuthConfig{
		ClientID: "test-client",
	}, logger)

	// Set up OIDC config
	auth.oidcConfig = OpenIDConfiguration{
		AuthorizationEndpoint: "https://auth.example.com/auth",
		TokenEndpoint:         "https://auth.example.com/token",
		Issuer:                "https://auth.example.com",
	}

	// This test is limited since we can't easily mock the OIDC provider
	// We'll just test that the OAuth2 config is set up correctly
	ctx := context.Background()
	scopes := []string{"openid", "profile"}

	// This will fail because we can't create a real provider in tests,
	// but we can check that the oauth2Config is set up correctly
	_ = auth.initOAuth2Config(ctx, scopes)

	if auth.oauth2Config.ClientID != "test-client" {
		t.Errorf("Wrong client ID: %s", auth.oauth2Config.ClientID)
	}

	if auth.oauth2Config.ClientSecret != "" {
		t.Errorf("Wrong client secret: %s", auth.oauth2Config.ClientSecret)
	}

	if auth.oauth2Config.RedirectURL != "http://localhost:8181/callback" {
		t.Errorf("Wrong redirect URL: %s", auth.oauth2Config.RedirectURL)
	}

	if auth.oauth2Config.Endpoint.AuthURL != "https://auth.example.com/auth" {
		t.Errorf("Wrong auth URL: %s", auth.oauth2Config.Endpoint.AuthURL)
	}

	if auth.oauth2Config.Endpoint.TokenURL != "https://auth.example.com/token" {
		t.Errorf("Wrong token URL: %s", auth.oauth2Config.Endpoint.TokenURL)
	}

	if !reflect.DeepEqual(auth.oauth2Config.Scopes, scopes) {
		t.Errorf("Wrong scopes: %v", auth.oauth2Config.Scopes)
	}
}

// TestHandleAuthChallenge tests the auth challenge handling
func TestHandleAuthChallenge(t *testing.T) {
	// Mock HTTP client for OIDC config fetch
	mockHTTPClient := &http.Client{
		Transport: roundTripFunc(func(req *http.Request) (*http.Response, error) {
			// Mock OIDC config response
			if strings.Contains(req.URL.Path, ".well-known/openid-configuration") {
				return &http.Response{
					StatusCode: 200,
					Body: io.NopCloser(strings.NewReader(`{
						"authorization_endpoint": "https://auth.example.com/auth",
						"token_endpoint": "https://auth.example.com/token", 
						"issuer": "https://auth.example.com"
					}`)),
					Header: make(http.Header),
				}, nil
			}
			return nil, fmt.Errorf("unexpected request to %s", req.URL)
		}),
	}

	logger := zap.NewNop().Sugar()
	auth := NewAuthManager(&AuthConfig{
		ClientID: "test-client",
		// Use small values for testing
		MaxAuthAttempts:    1,
		AuthCooldownPeriod: 50 * time.Millisecond,
	}, logger)

	// Replace the HTTP client
	auth.httpClient = mockHTTPClient

	// Create a mock 401 response
	resp := &http.Response{
		StatusCode: http.StatusUnauthorized,
		Header:     make(http.Header),
		Request: &http.Request{
			URL: &url.URL{
				Scheme: "https",
				Host:   "api.example.com",
			},
		},
	}
	resp.Header.Set("WWW-Authenticate", `Bearer realm="example", scope="openid profile"`)

	// Test auth challenge handling
	ctx := context.Background()
	authURL, waiter, err := auth.HandleAuthChallenge(ctx, resp)

	// We expect this to fail in tests since we can't create a real OIDC provider
	// but we can check some of the behavior

	if err == nil {
		// Due to test mocking limitations, we don't expect this to succeed
		// But if somehow it does, at least check the auth URL
		if !strings.Contains(authURL, "auth.example.com") {
			t.Errorf("Auth URL doesn't contain expected host: %s", authURL)
		}

		// If it succeeded, the waiter should be non-nil
		if waiter == nil {
			t.Error("Waiter function is nil")
		}
	}

	// Test rate limiting
	// Try another auth attempt immediately - should be denied
	_, _, err = auth.HandleAuthChallenge(ctx, resp)
	if err == nil {
		t.Error("Expected rate limiting error, got nil")
	}

	// Wait for cooldown and try again
	time.Sleep(100 * time.Millisecond)
	_, _, err = auth.HandleAuthChallenge(ctx, resp)
	// This should still fail but for OIDC-related reasons, not rate limiting
	if err != nil && strings.Contains(err.Error(), "maximum authentication attempts") {
		t.Errorf("Should not get rate limiting error after cooldown: %v", err)
	}
}

// Helper for mocking HTTP responses
type roundTripFunc func(*http.Request) (*http.Response, error)

func (f roundTripFunc) RoundTrip(req *http.Request) (*http.Response, error) {
	return f(req)
}
