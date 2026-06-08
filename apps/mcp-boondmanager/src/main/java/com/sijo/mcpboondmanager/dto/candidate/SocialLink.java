package com.sijo.mcpboondmanager.dto.candidate;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

/**
 * A candidate social-network handle ({@code network} + {@code url}), e.g. a LinkedIn profile URL.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record SocialLink(String network, String url) {
}