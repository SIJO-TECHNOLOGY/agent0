package com.sijo.mcpboondmanager.dto.boond;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

/**
 * A JSON:API "side-loaded" resource returned under the top-level {@code included} array. BoondManager
 * uses it to carry the attributes (names) of the resources referenced from a candidate's
 * {@link BoondRelationships} — e.g. the {@code resource} behind {@code mainManager}/{@code hrManager}
 * (with {@code firstName}/{@code lastName}) or the {@code agency} (with {@code name}).
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record BoondIncluded(
        String id,
        String type,
        IncludedAttributes attributes
) {

    /**
     * The subset of side-loaded attributes used for label resolution. {@code firstName}/{@code lastName}
     * are populated for {@code resource}-type entries (managers); {@code name} for {@code agency}-type
     * entries. Unknown keys are tolerated.
     */
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record IncludedAttributes(String firstName, String lastName, String name) {
    }
}