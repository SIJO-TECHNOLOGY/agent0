package com.sijo.mcpboondmanager.dto.dictionary;

import com.fasterxml.jackson.annotation.JsonAlias;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

/**
 * Reusable {@code id} + {@code label} dictionary entry. BoondManager sends the human-readable text
 * under {@code value}, which is aliased to {@code label} so it deserializes correctly while the
 * serialized output keeps the {@code label} name.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record DictionaryEntryDto(
        String id,
        @JsonAlias("value") String label
) {
}