package com.sijo.mcpboondmanager.dto.boond;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

import java.util.List;

/**
 * Attributes returned under {@code data.attributes} by {@code /technical-datas/{id}}.
 *
 * <p>BoondManager returns {@code diplomas}, {@code expertiseAreas} and {@code activityAreas} as JSON
 * arrays of strings, and {@code tools}/{@code languages} as arrays of objects (not delimited
 * strings), so they are modeled as typed lists. The endpoint does not expose a creation date or a
 * back-reference to the candidate id.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record BoondTechnicalDocumentAttributes(
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
        Boolean isReferent,
        String updateDate
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
