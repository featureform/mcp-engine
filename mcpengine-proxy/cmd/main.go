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
	ssePath := flag.String("sse_path", "/sse", "The path to append to hostname for an /sse connection")
	debug := flag.Bool("debug", false, "Enable debug logging")
	flag.Parse()

	var rawLogger *zap.Logger
	if *debug {
		l, err := zap.NewDevelopment()
		if err != nil {
			fmt.Errorf("Failed to setup logger: %s", err)
			os.Exit(1)
		}
		rawLogger = l
	} else {
		l, err := zap.NewProduction()
		if err != nil {
			fmt.Errorf("Failed to setup logger: %s", err)
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
		SSEPath:  *ssePath,
		AuthConfig: &mcpengine.AuthConfig{
			ClientID: *clientId,
		},
		Logger: logger,
	})
	if err != nil {
		logger.Fatalw("Failed to create MCPEngine", "err", err)
	}
	logger.Info("Starting MCPEngine")
	engine.Start(context.Background())
}
