package mcpengine

import (
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"sync"
	"time"

	"github.com/coreos/go-oidc"
	"go.uber.org/zap"
	"golang.org/x/oauth2"
)

// AuthConfig holds configuration options for AuthManager.
// Any field that is set to its zero value will be replaced with a default:
//   - ClientID:           ClientID to use for OAuth.
//   - ClientSecret:       ClientSecret to use for OAuth.
//   - ListenPort:         Port on which the auth server listens (default 8181)
//   - CallbackPath:       HTTP path for auth callbacks (default "/callback")
//   - OIDCConfigPath:     Path to fetch OIDC configuration (default "/.well-known/openid-configuration")
//   - MaxAuthAttempts:    Maximum allowed authentication attempts (default 3)
//   - AuthCooldownPeriod: Cooldown period between auth attempts (default 15 seconds)
type AuthConfig struct {
	ClientID           string
	ClientSecret       string
	ListenPort         int
	CallbackPath       string
	OIDCConfigPath     string
	MaxAuthAttempts    int
	AuthCooldownPeriod time.Duration
}

// resolveConfig fills in any missing configuration fields with defaults.
func resolveConfig(cfg *AuthConfig) *AuthConfig {
	if cfg == nil {
		return &AuthConfig{
			ListenPort:         8181,
			CallbackPath:       "/callback",
			OIDCConfigPath:     "/.well-known/openid-configuration",
			MaxAuthAttempts:    3,
			AuthCooldownPeriod: 15 * time.Second,
		}
	}

	resolved := *cfg
	if resolved.ListenPort == 0 {
		resolved.ListenPort = 8181
	}
	if resolved.CallbackPath == "" {
		resolved.CallbackPath = "/callback"
	}
	if resolved.OIDCConfigPath == "" {
		resolved.OIDCConfigPath = "/.well-known/openid-configuration"
	}
	if resolved.MaxAuthAttempts == 0 {
		resolved.MaxAuthAttempts = 3
	}
	if resolved.AuthCooldownPeriod == 0 {
		resolved.AuthCooldownPeriod = 15 * time.Second
	}
	return &resolved
}

// OpenIDConfiguration represents the OpenID Connect configuration.
type OpenIDConfiguration struct {
	AuthorizationEndpoint string `json:"authorization_endpoint"`
	TokenEndpoint         string `json:"token_endpoint"`
	Issuer                string `json:"issuer"`
}

// AuthManager handles the OpenID Connect authentication flow.
type AuthManager struct {
	redirectURL  string
	clientID     string
	clientSecret string
	opts         *AuthConfig

	server       *http.Server
	provider     *oidc.Provider
	oauth2Config oauth2.Config
	verifier     *oidc.IDTokenVerifier

	accessToken      string
	tokenMutex       sync.RWMutex
	authCompleteChan chan struct{}

	serverURL  string
	oidcConfig OpenIDConfiguration

	httpClient *http.Client
	logger     *zap.SugaredLogger

	// Auth retry tracking.
	authAttempts     int
	lastAuthAttempt  time.Time
	authAttemptsLock sync.Mutex
}

// NewAuthManager creates a new AuthManager instance.
// If a nil or partially populated config is provided, missing fields are replaced with defaults.
func NewAuthManager(cfg *AuthConfig, logger *zap.SugaredLogger) *AuthManager {
	cfg = resolveConfig(cfg)
	redirectURL := fmt.Sprintf("http://localhost:%d%s", cfg.ListenPort, cfg.CallbackPath)
	return &AuthManager{
		clientID:         cfg.ClientID,
		clientSecret:     cfg.ClientSecret,
		redirectURL:      redirectURL,
		opts:             cfg,
		authCompleteChan: make(chan struct{}),
		httpClient:       &http.Client{},
		logger:           logger,
	}
}

// CanAttemptAuth checks whether an authentication attempt is allowed based on the maximum attempts
// and the cooldown period. Returns an error if a new attempt is not permitted.
func (a *AuthManager) CanAttemptAuth() (bool, error) {
	a.authAttemptsLock.Lock()
	defer a.authAttemptsLock.Unlock()

	now := time.Now()
	if !a.lastAuthAttempt.IsZero() && now.Sub(a.lastAuthAttempt) < a.opts.AuthCooldownPeriod {
		waitDuration := a.opts.AuthCooldownPeriod - now.Sub(a.lastAuthAttempt)
		return false, fmt.Errorf("too many authentication attempts; please try again in %v", waitDuration.Round(time.Second))
	}
	if a.authAttempts >= a.opts.MaxAuthAttempts {
		if a.lastAuthAttempt.IsZero() || now.Sub(a.lastAuthAttempt) >= a.opts.AuthCooldownPeriod {
			a.logger.Debug("Resetting authentication attempt counter after cooldown")
			a.authAttempts = 0
		} else {
			return false, fmt.Errorf("maximum authentication attempts (%d) exceeded", a.opts.MaxAuthAttempts)
		}
	}
	a.authAttempts++
	a.lastAuthAttempt = now
	a.logger.Debugf("Authentication attempt %d of %d", a.authAttempts, a.opts.MaxAuthAttempts)
	return true, nil
}

// ResetAuthAttempts resets the authentication attempt counter,
// typically after a successful authentication.
func (a *AuthManager) ResetAuthAttempts() {
	a.authAttemptsLock.Lock()
	defer a.authAttemptsLock.Unlock()

	a.lastAuthAttempt = time.Time{}
	a.authAttempts = 0
	a.logger.Debug("Authentication attempt counter reset after successful token usage")
}

// HandleAuthChallenge handles a 401 response and starts the authentication flow.
// It returns the authorization URL, a waiter function that blocks until authentication completes,
// and an error.
func (a *AuthManager) HandleAuthChallenge(ctx context.Context, resp *http.Response) (string, func(), error) {
	canAttempt, err := a.CanAttemptAuth()
	if !canAttempt {
		return "", nil, fmt.Errorf("authentication not attempted: %w", err)
	}

	wwwAuth := resp.Header.Get("WWW-Authenticate")
	if wwwAuth == "" {
		return "", nil, fmt.Errorf("no WWW-Authenticate header in 401 response")
	}
	a.logger.Debugf("Received WWW-Authenticate header: %s", wwwAuth)

	scopes, err := parseScopes(wwwAuth)
	if err != nil {
		a.logger.Debugf("Error parsing scopes: %v; using default scopes", err)
		scopes = []string{oidc.ScopeOpenID, "profile", "email"}
	}

	serverURL, err := extractServerURL(resp.Request.URL)
	if err != nil {
		a.logger.Warnf("Failed to extract server URL: %v", err)
		return "", nil, fmt.Errorf("failed to extract server URL: %w", err)
	}
	a.serverURL = serverURL

	if err := a.fetchOIDCConfiguration(ctx); err != nil {
		return "", nil, fmt.Errorf("failed to fetch OIDC configuration: %w", err)
	}
	if err := a.initOAuth2Config(ctx, scopes); err != nil {
		return "", nil, fmt.Errorf("failed to initialize OAuth2 configuration: %w", err)
	}
	if err := a.startAuthServer(ctx); err != nil {
		return "", nil, fmt.Errorf("failed to start auth server: %w", err)
	}

	state := generateState()
	authURL := a.oauth2Config.AuthCodeURL(state)
	a.logger.Debugf("Started authentication flow with URL: %s", authURL)

	// Waiter blocks until the authentication flow is complete.
	waiter := func() {
		<-a.authCompleteChan
	}
	return authURL, waiter, nil
}

// GetAccessToken returns the current access token.
func (a *AuthManager) GetAccessToken() string {
	a.tokenMutex.RLock()
	defer a.tokenMutex.RUnlock()
	return a.accessToken
}

// fetchOIDCConfiguration retrieves the OpenID Connect configuration from the server.
func (a *AuthManager) fetchOIDCConfiguration(ctx context.Context) error {
	configURL := a.serverURL + a.opts.OIDCConfigPath
	a.logger.Debugf("Fetching OIDC configuration from %s", configURL)

	req, err := http.NewRequestWithContext(ctx, http.MethodGet, configURL, nil)
	if err != nil {
		return fmt.Errorf("failed to create request for OIDC configuration: %w", err)
	}

	resp, err := a.httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("failed to fetch OIDC configuration: %w", err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("failed to fetch OIDC configuration, status: %s", resp.Status)
	}

	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return fmt.Errorf("failed to read OIDC configuration response: %w", err)
	}

	if err := json.Unmarshal(body, &a.oidcConfig); err != nil {
		return fmt.Errorf("failed to parse OIDC configuration: %w", err)
	}
	a.logger.Debugf("OIDC configuration fetched: auth_endpoint=%s, token_endpoint=%s",
		a.oidcConfig.AuthorizationEndpoint, a.oidcConfig.TokenEndpoint)
	return nil
}

// initOAuth2Config initializes the OAuth2 configuration and OIDC provider.
func (a *AuthManager) initOAuth2Config(ctx context.Context, scopes []string) error {
	a.oauth2Config = oauth2.Config{
		ClientID:     a.clientID,
		ClientSecret: a.clientSecret,
		RedirectURL:  a.redirectURL,
		Endpoint: oauth2.Endpoint{
			AuthURL:  a.oidcConfig.AuthorizationEndpoint,
			TokenURL: a.oidcConfig.TokenEndpoint,
		},
		Scopes: scopes,
	}

	provider, err := oidc.NewProvider(ctx, a.oidcConfig.Issuer)
	if err != nil {
		return fmt.Errorf("failed to create OIDC provider: %w", err)
	}
	a.provider = provider
	a.verifier = provider.Verifier(&oidc.Config{ClientID: a.clientID})
	return nil
}

// startAuthServer starts an HTTP server to handle the authentication callback.
// It accepts a context that, when canceled, will cause the server to shut down gracefully.
func (a *AuthManager) startAuthServer(ctx context.Context) error {
	mux := http.NewServeMux()
	mux.HandleFunc(a.opts.CallbackPath, a.handleCallback)

	a.server = &http.Server{
		Addr:    fmt.Sprintf(":%d", a.opts.ListenPort),
		Handler: mux,
	}
	a.logger.Debugf("Starting authentication server on port %d", a.opts.ListenPort)

	// Listen for context cancellation to shut down the server.
	go func() {
		<-ctx.Done()
		a.logger.Debug("Context canceled; shutting down auth server")
		shutdownCtx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		if err := a.server.Shutdown(shutdownCtx); err != nil {
			a.logger.Errorf("Error shutting down auth server: %v", err)
		}
	}()

	go func() {
		if err := a.server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			a.logger.Errorf("HTTP server error: %v", err)
		}
	}()
	return nil
}

// handleCallback processes the authentication callback request.
func (a *AuthManager) handleCallback(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	code := r.URL.Query().Get("code")
	if code == "" {
		http.Error(w, "missing code in request", http.StatusBadRequest)
		return
	}

	oauth2Token, err := a.oauth2Config.Exchange(ctx, code)
	if err != nil {
		http.Error(w, "failed to exchange token: "+err.Error(), http.StatusInternalServerError)
		return
	}

	a.tokenMutex.Lock()
	a.accessToken = oauth2Token.AccessToken
	a.tokenMutex.Unlock()

	w.Header().Set("Content-Type", "text/html")
	w.Write([]byte(`
		<html>
		  <head><title>Authentication Successful</title></head>
		  <body>
			<h1>Authentication Successful</h1>
			<p>You can now close this window and return to the application.</p>
		  </body>
		</html>
	`))

	go func() {
		time.Sleep(1 * time.Second)
		a.shutdown()
		close(a.authCompleteChan)
	}()
}

// shutdown gracefully stops the authentication server.
func (a *AuthManager) shutdown() {
	if a.server != nil {
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()

		a.logger.Debug("Shutting down authentication server")
		if err := a.server.Shutdown(ctx); err != nil {
			a.logger.Errorf("Error shutting down server: %v", err)
		}
	}
}

// parseScopes extracts scopes from the WWW-Authenticate header.
func parseScopes(header string) ([]string, error) {
	if !strings.HasPrefix(header, "Bearer ") {
		return nil, fmt.Errorf("invalid WWW-Authenticate header, expected Bearer token: %s", header)
	}

	parts := strings.Split(strings.TrimPrefix(header, "Bearer "), ",")
	for _, part := range parts {
		part = strings.TrimSpace(part)
		if strings.HasPrefix(part, "scope=") {
			scopesVal := part[len("scope="):]
			scopesVal = strings.Trim(scopesVal, "\"")
			rawScopes := strings.Fields(scopesVal)
			var scopes []string
			for _, rawScope := range rawScopes {
				scope := strings.Trim(rawScope, "'")
				scopes = append(scopes, scope)
			}
			return scopes, nil
		}
	}
	// Fallback to default scopes if none found.
	return []string{oidc.ScopeOpenID, "profile", "email"}, nil
}

// extractServerURL constructs the base URL from the provided URL.
func extractServerURL(u *url.URL) (string, error) {
	if u == nil {
		return "", fmt.Errorf("nil URL provided")
	}
	return fmt.Sprintf("%s://%s", u.Scheme, u.Host), nil
}

// generateState creates a random state string for CSRF protection.
func generateState() string {
	b := make([]byte, 32)
	if _, err := rand.Read(b); err != nil {
		// Fallback: use a timestamp if random generation fails.
		return fmt.Sprintf("%d", time.Now().UnixNano())
	}
	return base64.StdEncoding.EncodeToString(b)
}
