package com.sijo.mcpboondmanager.infrastructure;

import jakarta.servlet.FilterChain;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.slf4j.MDC;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.mock.web.MockHttpServletResponse;

import java.util.UUID;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;

class CorrelationIdFilterTest {

    private CorrelationIdFilter filter;

    @BeforeEach
    void setUp() {
        filter = new CorrelationIdFilter();
        MDC.clear();
    }

    @AfterEach
    void tearDown() {
        MDC.clear();
    }

    @Test
    void givenRequestHasCorrelationId_whenFiltered_thenReusesCorrelationId() throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest("GET", "/mcp");
        request.addHeader(CorrelationIdFilter.HEADER_NAME, "corr-123");
        MockHttpServletResponse response = new MockHttpServletResponse();
        AtomicReference<String> mdcDuringRequest = new AtomicReference<>();

        filter.doFilter(request, response, chainCapturingMdc(mdcDuringRequest));

        assertThat(mdcDuringRequest.get()).isEqualTo("corr-123");
        assertThat(response.getHeader(CorrelationIdFilter.HEADER_NAME)).isEqualTo("corr-123");
        assertThat(request.getAttribute(MdcKeys.CORRELATION_ID)).isEqualTo("corr-123");
        assertThat(MDC.get(MdcKeys.CORRELATION_ID)).isNull();
    }

    @Test
    void givenRequestHasNoCorrelationId_whenFiltered_thenGeneratesCorrelationId() throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest("GET", "/mcp");
        MockHttpServletResponse response = new MockHttpServletResponse();
        AtomicReference<String> mdcDuringRequest = new AtomicReference<>();

        filter.doFilter(request, response, chainCapturingMdc(mdcDuringRequest));

        String generatedId = response.getHeader(CorrelationIdFilter.HEADER_NAME);
        assertThat(generatedId)
                .isNotBlank()
                .isEqualTo(mdcDuringRequest.get())
                .isEqualTo(request.getAttribute(MdcKeys.CORRELATION_ID));
        assertThatCode(() -> UUID.fromString(generatedId)).doesNotThrowAnyException();
    }

    @Test
    void givenRequestCompletes_whenFiltered_thenMdcIsClearedAfterRequest() throws Exception {
        MockHttpServletRequest request = new MockHttpServletRequest("GET", "/mcp");
        MockHttpServletResponse response = new MockHttpServletResponse();

        filter.doFilter(request, response, (servletRequest, servletResponse) ->
                assertThat(MDC.get(MdcKeys.CORRELATION_ID)).isNotBlank()
        );

        assertThat(MDC.get(MdcKeys.CORRELATION_ID)).isNull();
    }

    private FilterChain chainCapturingMdc(AtomicReference<String> mdcDuringRequest) {
        return (servletRequest, servletResponse) ->
                mdcDuringRequest.set(MDC.get(MdcKeys.CORRELATION_ID));
    }
}
