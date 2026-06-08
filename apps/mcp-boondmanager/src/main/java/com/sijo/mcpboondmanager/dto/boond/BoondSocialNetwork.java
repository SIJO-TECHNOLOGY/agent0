package com.sijo.mcpboondmanager.dto.boond;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

/**
 * A social-network handle as returned by BoondManager under {@code socialNetworks[]} on the candidate
 * search and {@code /information} payloads ({@code {"network": "linkedin", "url": ...}}).
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record BoondSocialNetwork(String network, String url) {
}