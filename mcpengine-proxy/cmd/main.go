package main

import (
	"context"
	"flag"
	"fmt"
	"os"

	"go.uber.org/zap"

	"mcpengine"
)

func main() {
	host := flag.String("host", "localhost:8000", "The hostname. By default we connect to <hostname>/sse")
	clientId := flag.String("client_id", "", "The ClientID to be used in OAuth")
	clientSecret := flag.String("client_secret", "", "The Client Secret to be used in OAuth")
	mode := flag.String("mode", "sse", "The style of HTTP communication to use with the server (one of: sse, http)")
	ssePath := flag.String("sse_path", "/sse", "The path to append to hostname for an /sse connection")
	mcpPath := flag.String("mcp_path", "/mcp", "The path to append to hostname for non-SSE POST")
	debug := flag.Bool("debug", false, "Enable debug logging")
	flag.Parse()

	if *mode != "sse" && *mode != "http" {
		fmt.Printf("Invalid mode: %s. Must be one of \"sse\", \"http\"\n", *mode)
		os.Exit(1)
	}

	var rawLogger *zap.Logger
	if *debug {
		l, err := zap.NewDevelopment()
		if err != nil {
			fmt.Printf("Failed to setup logger: %s\n", err)
			os.Exit(1)
		}
		rawLogger = l
	} else {
		l, err := zap.NewProduction()
		if err != nil {
			fmt.Printf("Failed to setup logger: %s\n", err)
			os.Exit(1)
		}
		rawLogger = l
	}
	logger := rawLogger.Sugar()

	if *host == "" {
		logger.Fatal("-host flag must be set")
	}
	engine, err := mcpengine.New(mcpengine.Config{
		Endpoint: *host,
		UseSSE:   *mode == "sse",
		SSEPath:  *ssePath,
		MCPPath:  *mcpPath,
		AuthConfig: &mcpengine.AuthConfig{
			ClientID:     *clientId,
			ClientSecret: *clientSecret,
		},
		Logger: logger,
	})
	if err != nil {
		logger.Fatalw("Failed to create MCPEngine", "err", err)
	}
	logger.Info("Starting MCPEngine")
	engine.Start(context.Background())
}
