package com.sijo.mcpboondmanager.dto.boond;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

import java.util.List;

/**
 * Attributes returned under {@code data.attributes} by the candidate-scoped tab
 * {@code GET /candidates/{candidateId}/technical-data}.
 *
 * <p>The candidate id is only the {@code {candidateId}} path segment used to reach this tab;
 * BoondManager resolves the candidate → DT link server-side and returns the candidate's technical
 * document (DT) resource. That resource has its <strong>own</strong> identifier ({@code ID_DT}),
 * carried both as {@code data.id} and, redundantly, in the {@code tdId} attribute — it is distinct
 * from the candidate id ({@code ID_PROFIL}). The two ids must never be treated as interchangeable,
 * and the candidate id is never used as a technical-data id.
 *
 * <p>BoondManager returns {@code diplomas}, {@code expertiseAreas} and {@code activityAreas} as JSON
 * arrays of strings, and {@code tools}/{@code languages} as arrays of objects (not delimited
 * strings), so they are modeled as typed lists.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record BoondTechnicalDocumentAttributes(
        String tdId,
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
        List<Language> languages
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
