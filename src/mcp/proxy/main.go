package main

import (
	"fmt"
	"log"
	"os"
	"os/signal"
	"syscall"

	"github.com/featureform/stdiosseproxy/proxy"
)

func main() {
	// Check if the URL and optional log file are provided as arguments
	if len(os.Args) < 2 {
		fmt.Fprintln(os.Stderr, "Usage: stdiosseproxy <server-url> [log-file]")
		os.Exit(1)
	}

	serverURL := os.Args[1]

	// Set up logging
	var logger *log.Logger
	if len(os.Args) > 2 {
		logFilePath := os.Args[2]
		logFile, err := os.OpenFile(logFilePath, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0666)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error opening log file: %v\n", err)
			os.Exit(1)
		}
		defer logFile.Close()
		logger = log.New(logFile, "SSE-PROXY: ", log.Ldate|log.Ltime|log.Lshortfile)
	} else {
		// By default, logs go to stderr
		logger = log.New(os.Stderr, "SSE-PROXY: ", log.Ldate|log.Ltime|log.Lshortfile)
	}

	logger.Println("Starting SSE proxy to server:", serverURL)
	logger.Println("Using MCP protocol version: 2024-11-05")

	// Create the proxy server
	proxyServer := proxy.NewProxyServer(serverURL, logger)

	// Create a channel to signal shutdown
	shutdown := make(chan os.Signal, 1)
	signal.Notify(shutdown, os.Interrupt, syscall.SIGTERM)

	// Start the proxy in a goroutine
	errChan := make(chan error, 1)
	go func() {
		errChan <- proxyServer.Start()
	}()

	// Wait for shutdown signal or error
	select {
	case <-shutdown:
		logger.Println("Received shutdown signal, closing connections...")
		proxyServer.Stop()
	case err := <-errChan:
		logger.Printf("Proxy terminated with error: %v", err)
	}
}
