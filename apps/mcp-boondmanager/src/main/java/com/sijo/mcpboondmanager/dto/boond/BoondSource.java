package com.sijo.mcpboondmanager.dto.boond;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

/**
 * Sourcing origin of a candidate as returned under the {@code source} object on the
 * {@code /candidates} search payload: {@code typeOf} is the source-type id (resolvable through
 * {@code getDictionary: setting.source}) and {@code detail} is the free-text precision.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record BoondSource(Integer typeOf, String detail) {
}