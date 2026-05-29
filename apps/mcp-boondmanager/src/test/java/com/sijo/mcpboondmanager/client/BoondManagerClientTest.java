package com.sijo.mcpboondmanager.client;

import com.sijo.mcpboondmanager.config.BoondManagerProperties;
import com.sijo.mcpboondmanager.config.WebClientConfig;
import com.sijo.mcpboondmanager.dto.boond.BoondCandidateDetailAttributes;
import com.sijo.mcpboondmanager.dto.boond.BoondCandidateSummaryAttributes;
import com.sijo.mcpboondmanager.dto.boond.BoondDictionaryAttributes;
import com.sijo.mcpboondmanager.dto.boond.BoondListEnvelope;
import com.sijo.mcpboondmanager.dto.boond.BoondSingleEnvelope;
import com.sijo.mcpboondmanager.exception.BoondApiException;
import com.sijo.mcpboondmanager.exception.ExternalServiceException;
import com.sijo.mcpboondmanager.infrastructure.CorrelationIdFilter;
import com.sijo.mcpboondmanager.infrastructure.MdcKeys;
import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.slf4j.MDC;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.HttpStatus;
import org.springframework.util.unit.DataSize;

import java.io.IOException;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class BoondManagerClientTest {

    private static final ParameterizedTypeReference<BoondSingleEnvelope<BoondDictionaryAttributes>> DICTIONARY_TYPE =
            new ParameterizedTypeReference<>() {};
    private static final ParameterizedTypeReference<BoondListEnvelope<BoondCandidateSummaryAttributes>> SEARCH_TYPE =
            new ParameterizedTypeReference<>() {};
    private static final ParameterizedTypeReference<BoondSingleEnvelope<BoondCandidateDetailAttributes>> DETAIL_TYPE =
            new ParameterizedTypeReference<>() {};

    private HttpServer server;
    private ExecutorService executor;
    private AtomicReference<CapturedRequest> capturedRequest;

    @BeforeEach
    void setUp() throws IOException {
        capturedRequest = new AtomicReference<>();
        executor = Executors.newCachedThreadPool();
        server = HttpServer.create(new InetSocketAddress(0), 0);
        server.setExecutor(executor);
        server.start();
        MDC.clear();
    }

    @AfterEach
    void tearDown() {
        MDC.clear();
        if (server != null) {
            server.stop(0);
        }
        if (executor != null) {
            executor.shutdownNow();
        }
    }

    @Test
    void givenDictionaryEndpoint_whenGet_thenDeserializesEnvelopeAndSendsAuthAndCorrelationHeaders() {
        respondJson("/application/dictionary", 200, """
                {
                  "data": {
                    "id": "dictionary",
                    "type": "setting",
                    "attributes": {
                      "state": {"candidate": [{"id": "1", "value": "Active"}]},
                      "availability": [{"id": "9", "value": "Available"}],
                      "mobilityArea": [{"option": [{"id": "idf", "value": "Paris"}], "value": "Ile-de-France"}]
                    }
                  }
                }
                """);
        MDC.put(MdcKeys.CORRELATION_ID, "corr-123");

        BoondSingleEnvelope<BoondDictionaryAttributes> response = client(Duration.ofSeconds(2))
                .get("/application/dictionary", DICTIONARY_TYPE);

        assertThat(response.data().id()).isEqualTo("dictionary");
        assertThat(response.data().attributes().state().candidate())
                .extracting("id", "label")
                .containsExactly(org.assertj.core.groups.Tuple.tuple("1", "Active"));
        assertThat(capturedRequest.get().method()).isEqualTo("GET");
        assertThat(capturedRequest.get().path()).isEqualTo("/application/dictionary");
        assertThat(capturedRequest.get().header(CorrelationIdFilter.HEADER_NAME)).isEqualTo("corr-123");
        assertThat(capturedRequest.get().header(WebClientConfig.JWT_CLIENT_HEADER)).isEqualTo("test-jwt");
    }

    @Test
    void givenSearchEndpointWithQueryParams_whenGet_thenPassesNonNullParamsAndOmitsOthers() {
        respondJson("/candidates", 200, """
                {
                  "data": [
                    {
                      "id": "42",
                      "type": "candidate",
                      "attributes": {"firstName": "Ada", "lastName": "Lovelace"}
                    }
                  ],
                  "meta": {"totals": {"rows": 1}, "currentPage": 1}
                }
                """);

        BoondListEnvelope<BoondCandidateSummaryAttributes> response = client(Duration.ofSeconds(2))
                .get("/candidates", builder -> {
                    builder.queryParam("keywords", "java");
                    builder.queryParam("page", 1);
                    builder.queryParam("numberPerPage", 25);
                }, SEARCH_TYPE);

        assertThat(response.data()).hasSize(1);
        assertThat(response.data().getFirst().id()).isEqualTo("42");
        assertThat(response.data().getFirst().attributes().firstName()).isEqualTo("Ada");
        assertThat(response.meta().totals().rows()).isEqualTo(1);
        assertThat(capturedRequest.get().query())
                .isEqualTo("keywords=java&page=1&numberPerPage=25");
    }

    @Test
    void givenCandidateDetailEndpoint_whenGet_thenDeserializesSingleEnvelope() {
        respondJson("/candidates/42", 200, """
                {
                  "data": {
                    "id": "42",
                    "type": "candidate",
                    "attributes": {
                      "firstName": "Ada",
                      "lastName": "Lovelace",
                      "email": "ada@example.test",
                      "technicalDocumentId": 101
                    }
                  }
                }
                """);

        BoondSingleEnvelope<BoondCandidateDetailAttributes> response = client(Duration.ofSeconds(2))
                .get("/candidates/42", DETAIL_TYPE);

        assertThat(response.data().id()).isEqualTo("42");
        assertThat(response.data().attributes().email()).isEqualTo("ada@example.test");
        assertThat(response.data().attributes().technicalDocumentId()).isEqualTo(101);
    }

    @Test
    void givenBackend400_whenGet_thenMapsToBoondApiExceptionWithStatus() {
        respondJson("/bad-request", 400, "{\"error\":\"bad input\"}");

        assertThatThrownBy(() -> client(Duration.ofSeconds(2)).get("/bad-request", DICTIONARY_TYPE))
                .isInstanceOfSatisfying(BoondApiException.class, ex -> {
                    assertThat(ex.status()).isEqualTo(HttpStatus.BAD_REQUEST);
                    assertThat(ex.path()).isEqualTo("/bad-request");
                })
                .hasMessageContaining("BoondManager returned 400 BAD_REQUEST")
                .hasMessageContaining("GET /bad-request");
    }

    @ParameterizedTest
    @ValueSource(ints = {401, 403})
    void givenUnauthorizedOrForbiddenBackendResponse_whenGet_thenDoesNotLeakResponseBody(int status) {
        respondJson("/secure", status, "{\"token\":\"secret-token-value\"}");

        BoondManagerClient client = client(Duration.ofSeconds(2));
        assertThatThrownBy(() -> client.get("/secure", DICTIONARY_TYPE))
                .isInstanceOf(BoondApiException.class)
                .hasMessageContaining("GET /secure")
                .hasMessageNotContaining("secret-token-value");
    }

    @Test
    void givenBackend404_whenGet_thenMapsToBoondApiExceptionWithNotFoundStatus() {
        respondJson("/missing", 404, "{\"message\":\"not found\"}");

        assertThatThrownBy(() -> client(Duration.ofSeconds(2)).get("/missing", DICTIONARY_TYPE))
                .isInstanceOfSatisfying(BoondApiException.class, ex ->
                        assertThat(ex.status()).isEqualTo(HttpStatus.NOT_FOUND))
                .hasMessageContaining("404 NOT_FOUND")
                .hasMessageContaining("GET /missing");
    }

    @Test
    void givenBackend500_whenGet_thenMapsToBoondApiException() {
        respondJson("/candidates", 500, "{\"message\":\"backend down\"}");

        assertThatThrownBy(() -> client(Duration.ofSeconds(2)).get("/candidates", SEARCH_TYPE))
                .isInstanceOfSatisfying(BoondApiException.class, ex ->
                        assertThat(ex.status()).isEqualTo(HttpStatus.INTERNAL_SERVER_ERROR))
                .hasMessageContaining("500 INTERNAL_SERVER_ERROR")
                .hasMessageContaining("GET /candidates");
    }

    @Test
    void givenSlowBackend_whenGet_thenTimeoutMapsToExternalServiceException() {
        server.createContext("/slow", exchange -> {
            capturedRequest.set(capture(exchange));
            try {
                Thread.sleep(1_000);
                writeJson(exchange, 200, "{}");
            } catch (InterruptedException ex) {
                Thread.currentThread().interrupt();
            } catch (IOException ignored) {
                // The client is expected to close the exchange after the configured timeout.
            }
        });
        BoondManagerClient client = client(Duration.ofMillis(100));
        assertThatThrownBy(() -> client.get("/slow", DICTIONARY_TYPE))
                .isInstanceOf(ExternalServiceException.class)
                .hasMessageContaining("/slow");
    }

    @Test
    void givenBaseUrlFromProperties_whenGet_thenUsesConfiguredServer() {
        respondJson("/base-url-check", 200, "{\"data\": {\"id\": \"x\", \"type\": \"setting\", \"attributes\": {}}}");

        BoondSingleEnvelope<BoondDictionaryAttributes> response = client(Duration.ofSeconds(2))
                .get("/base-url-check", DICTIONARY_TYPE);

        assertThat(response.data().id()).isEqualTo("x");
        assertThat(capturedRequest.get().path()).isEqualTo("/base-url-check");
    }

    @Test
    void givenMissingCorrelationIdInMdc_whenGet_thenSendsEmptyHeader() {
        respondJson("/no-corr", 200, "{\"data\": {\"id\": \"x\", \"type\": \"setting\", \"attributes\": {}}}");

        client(Duration.ofSeconds(2)).get("/no-corr", DICTIONARY_TYPE);

        assertThat(capturedRequest.get().header(CorrelationIdFilter.HEADER_NAME)).isEmpty();
    }

    private BoondManagerClient client(Duration timeout) {
        BoondManagerProperties properties = properties(timeout);
        return new BoondManagerClient(new WebClientConfig().boondManagerWebClient(properties));
    }

    private BoondManagerProperties properties(Duration timeout) {
        return new BoondManagerProperties(
                "http://localhost:" + server.getAddress().getPort(),
                "test-jwt",
                timeout,
                new BoondManagerProperties.Webclient(DataSize.ofMegabytes(16)));
    }

    private void respondJson(String path, int status, String body) {
        server.createContext(path, exchange -> {
            capturedRequest.set(capture(exchange));
            writeJson(exchange, status, body);
        });
    }

    private CapturedRequest capture(HttpExchange exchange) throws IOException {
        String correlation = exchange.getRequestHeaders().getFirst(CorrelationIdFilter.HEADER_NAME);
        String jwt = exchange.getRequestHeaders().getFirst(WebClientConfig.JWT_CLIENT_HEADER);
        return new CapturedRequest(
                exchange.getRequestMethod(),
                exchange.getRequestURI().getPath(),
                exchange.getRequestURI().getRawQuery(),
                correlation,
                jwt,
                new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8)
        );
    }

    private void writeJson(HttpExchange exchange, int status, String body) throws IOException {
        byte[] bytes = body.getBytes(StandardCharsets.UTF_8);
        exchange.getResponseHeaders().set("Content-Type", "application/json");
        exchange.sendResponseHeaders(status, bytes.length);
        exchange.getResponseBody().write(bytes);
        exchange.close();
    }

    private record CapturedRequest(
            String method,
            String path,
            String query,
            String correlationId,
            String jwt,
            String body
    ) {
        String header(String name) {
            if (CorrelationIdFilter.HEADER_NAME.equalsIgnoreCase(name)) {
                return correlationId == null ? "" : correlationId;
            }
            if (WebClientConfig.JWT_CLIENT_HEADER.equalsIgnoreCase(name)) {
                return jwt;
            }
            return null;
        }
    }
}