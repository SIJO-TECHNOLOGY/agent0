package com.sijo.mcpboondmanager.dto.boond;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

import java.util.List;

/**
 * Attributes returned under {@code data.attributes} by the candidate-scoped endpoint
 * {@code /candidates/{candidateId}/technical-data}.
 *
 * <p>This endpoint is keyed by the <strong>candidate</strong> id (so {@code data.id} is the
 * candidate id) and returns that candidate's own technical document. The technical document's own
 * identifier is carried in the {@code tdId} attribute. (Note: the sibling collection endpoint
 * {@code /technical-datas/{id}} is keyed by the technical-document id instead, so it must not be
 * called with a candidate id.)
 *
 * <p>BoondManager returns {@code diplomas}, {@code expertiseAreas} and {@code activityAreas} as JSON
 * arrays of strings, and {@code tools}/{@code languages}/{@code references} as arrays of objects (not
 * delimited strings), so they are modeled as typed lists. {@code references} is the candidate's
 * detailed assignment history ({@link BoondReference}) and is the richest free-text matching signal —
 * it must never be flattened or truncated.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record BoondTechnicalDocumentAttributes(
        String tdId,
        String tdLink,
        String title,
        String description,
        String summary,
        Integer experience,
        String training,
        List<String> diplomas,
        String skills,
        List<String> expertiseAreas,
        List<String> activityAreas,
        List<Tool> tools,
        List<Language> languages,
        List<BoondReference> references
) {

    /**
     * A tool/technology mastered by the candidate with its proficiency level (BoondManager sends an
     * integer level under {@code tools[].level}).
     */
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Tool(String tool, Integer level) {
    }

    /**
     * A spoken language with its level, as returned under {@code languages[]}
     * ({@code {"language": ..., "level": ...}}).
     */
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record Language(String language, String level) {
    }
}
