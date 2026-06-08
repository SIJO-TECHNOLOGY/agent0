package com.sijo.mcpboondmanager.dto.boond;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

/**
 * The {@code relationships} object of a JSON:API candidate resource. BoondManager links a candidate to
 * other resources (its managers, agency, …) here as {@code {"data": {"id": ..., "type": ...}}} refs;
 * the referenced resources' attributes (names) are resolved from the sibling {@code included} array
 * (see {@link BoondIncluded}).
 *
 * <p>Only the relationships carrying a recruitment signal are modeled ({@code mainManager},
 * {@code hrManager}, {@code agency}); other links ({@code createdBy}, {@code pole}, {@code resumes}, …)
 * are ignored. Unknown keys are tolerated.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record BoondRelationships(
        Relationship mainManager,
        Relationship hrManager,
        Relationship agency
) {

    /** A single relationship link wrapping its {@code data} reference (id + type). */
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Relationship(ResourceRef data) {
    }

    /** A JSON:API resource reference ({@code id} + {@code type}) pointing into {@code included}. */
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record ResourceRef(String id, String type) {
    }
}