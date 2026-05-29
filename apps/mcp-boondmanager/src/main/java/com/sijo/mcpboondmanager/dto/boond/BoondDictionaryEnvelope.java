package com.sijo.mcpboondmanager.dto.boond;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

/**
 * Envelope dedicated to the {@code /application/dictionary} endpoint.
 *
 * <p>Unlike the standard BoondManager JSON:API resources (handled by
 * {@link BoondSingleEnvelope} via {@code data.id} / {@code data.type} / {@code data.attributes}),
 * this endpoint returns a flat business object directly under {@code data}. This envelope is
 * scoped to that endpoint only and must not be reused for JSON:API resources.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record BoondDictionaryEnvelope(
        BoondDictionaryData data
) {
}