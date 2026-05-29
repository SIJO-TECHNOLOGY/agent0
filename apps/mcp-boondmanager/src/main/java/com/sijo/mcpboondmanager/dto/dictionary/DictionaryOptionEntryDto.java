package com.sijo.mcpboondmanager.dto.dictionary;

import com.fasterxml.jackson.annotation.JsonAlias;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

import java.util.List;

/**
 * Dictionary entry whose value is split into sub-options, as returned for
 * {@code setting.mobilityArea} (and other hierarchical lists) by {@code /application/dictionary}.
 *
 * <p>Each entry carries a list of {@link OptionId} sub-options under {@code option} — BoondManager
 * sends a JSON array there, not a single object. The human-readable text is sent under {@code value}
 * (aliased to {@code label}).
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record DictionaryOptionEntryDto(
        List<OptionId> option,
        @JsonAlias("value") String label
) {
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record OptionId(
            String id,
            @JsonAlias("value") String label
    ) {
    }
}