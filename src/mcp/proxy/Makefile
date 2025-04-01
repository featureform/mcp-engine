.PHONY: build test clean integration-test debug-connection

build:
	go build -o stdiosseproxy .

test:
	go test -v ./proxy

integration-test:
	RUN_INTEGRATION_TESTS=1 go test -v ./integration

debug-connection:
	go run integration/cmd/debug_connection.go

clean:
	rm -f stdiosseproxy
