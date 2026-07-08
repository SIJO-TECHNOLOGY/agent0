package com.sijo.mcpboondmanager.client;

import com.sijo.mcpboondmanager.exception.BoondApiException;
import com.sijo.mcpboondmanager.exception.ExternalServiceException;
import com.sijo.mcpboondmanager.infrastructure.CorrelationIdFilter;
import com.sijo.mcpboondmanager.infrastructure.MdcKeys;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.stereotype.Component;
import org.springframework.web.reactive.function.client.WebClient;
import org.springframework.web.reactive.function.client.WebClientRequestException;
import org.springframework.web.reactive.function.client.WebClientResponseException;
import org.springframework.web.util.UriBuilder;

import java.time.Duration;
import java.util.function.Consumer;

@Component
public class BoondManagerClient {

    private static final Logger log = LoggerFactory.getLogger(BoondManagerClient.class);

    private final WebClient webClient;

    public BoondManagerClient(WebClient boondManagerWebClient) {
        this.webClient = boondManagerWebClient;
    }

    public <T> T get(String path, ParameterizedTypeReference<T> responseType) {
        return get(path, builder -> {}, responseType);
    }

    public byte[] getBytes(String path) {
        return getBytes(path, null, null);
    }

    /**
     * Downloads binary content from BoondManager.
     *
     * @param path            relative API path
     * @param timeoutOverride per-call timeout; when null the WebClient default applies
     * @param acceptOverride  Accept header value; when null the WebClient default (application/json) applies
     */
    public byte[] getBytes(String path, Duration timeoutOverride, String acceptOverride) {
        String correlationId = MDC.get(MdcKeys.CORRELATION_ID);
        log.debug("Calling BoondManager GET (bytes) {} accept={}", path, acceptOverride);
        try {
            var spec = webClient.get()
                    .uri(path)
                    .header(CorrelationIdFilter.HEADER_NAME, correlationId == null ? "" : correlationId);
            if (acceptOverride != null) {
                spec = spec.header("Accept", acceptOverride);
            }
            var mono = spec.retrieve().bodyToMono(byte[].class);
            if (timeoutOverride != null) {
                mono = mono.timeout(timeoutOverride);
            }
            return mono.block();
        } catch (WebClientResponseException ex) {
            throw new BoondApiException(
                    "BoondManager returned " + ex.getStatusCode() + " on GET " + path,
                    ex.getStatusCode(),
                    path,
                    ex);
        } catch (WebClientRequestException ex) {
            throw new ExternalServiceException(
                    "Unable to reach BoondManager on GET " + path, path, ex);
        } catch (RuntimeException ex) {
            String causeMessage = ex.getMessage();
            String detail = causeMessage == null || causeMessage.isBlank()
                    ? ex.getClass().getSimpleName()
                    : ex.getClass().getSimpleName() + ": " + causeMessage;
            throw new ExternalServiceException(
                    "Unexpected error while calling BoondManager on GET " + path + " (" + detail + ")",
                    path,
                    ex);
        }
    }

    public <T> T get(String path,
                     Consumer<UriBuilder> uriCustomizer,
                     ParameterizedTypeReference<T> responseType) {
        String correlationId = MDC.get(MdcKeys.CORRELATION_ID);
        log.debug("Calling BoondManager GET {}", path);
        try {
            return webClient.get()
                    .uri(uriBuilder -> {
                        uriBuilder.path(path);
                        uriCustomizer.accept(uriBuilder);
                        return uriBuilder.build();
                    })
                    .header(CorrelationIdFilter.HEADER_NAME, correlationId == null ? "" : correlationId)
                    .retrieve()
                    .bodyToMono(responseType)
                    .block();
        } catch (WebClientResponseException ex) {
            throw new BoondApiException(
                    "BoondManager returned " + ex.getStatusCode() + " on GET " + path,
                    ex.getStatusCode(),
                    path,
                    ex);
        } catch (WebClientRequestException ex) {
            throw new ExternalServiceException(
                    "Unable to reach BoondManager on GET " + path, path, ex);
        } catch (RuntimeException ex) {
            String causeMessage = ex.getMessage();
            String detail = causeMessage == null || causeMessage.isBlank()
                    ? ex.getClass().getSimpleName()
                    : ex.getClass().getSimpleName() + ": " + causeMessage;
            throw new ExternalServiceException(
                    "Unexpected error while calling BoondManager on GET " + path + " (" + detail + ")",
                    path,
                    ex);
        }
    }
}
