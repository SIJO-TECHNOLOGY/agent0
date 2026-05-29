package com.sijo.mcpboondmanager.transport;

import org.junit.jupiter.api.Test;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.client.RestClient;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest(
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
        properties = {
                "boondmanager.base-url=http://localhost:9999",
                "boondmanager.jwt-client=test-jwt",
                "boondmanager.timeout=5s"
        })
class StreamableHttpTransportTest {

    @LocalServerPort
    private int port;

    @Test
    void initializeReturnsStreamableHttpHandshakeWithServerInfo() {
        String body = """
                {
                  "jsonrpc": "2.0",
                  "id": 1,
                  "method": "initialize",
                  "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "mcp-boondmanager-test", "version": "0.0.1"}
                  }
                }
                """;

        ResponseEntity<String> response = RestClient.create()
                .post()
                .uri("http://localhost:" + port + "/mcp")
                .contentType(MediaType.APPLICATION_JSON)
                .accept(MediaType.APPLICATION_JSON, MediaType.TEXT_EVENT_STREAM)
                .body(body)
                .retrieve()
                .toEntity(String.class);

        assertThat(response.getStatusCode().is2xxSuccessful())
                .as("Streamable HTTP /mcp endpoint must accept initialize POSTs")
                .isTrue();
        assertThat(response.getBody())
                .as("Server info must be present in handshake response")
                .contains("mcp-boondmanager");
    }
}