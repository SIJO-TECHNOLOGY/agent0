package com.sijo.mcpboondmanager.dto.candidate;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

import java.util.List;

/**
 * Candidate technical document (CV / skills profile).
 *
 * <p>{@code id} is the id of the candidate the document belongs to (the endpoint is candidate
 * scoped); {@code tdId} is the technical document's own identifier.
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record TechnicalDocumentDto(
        Integer id,
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
        List<ToolProficiency> tools,
        List<LanguageProficiency> languages,
        Integer candidateId
) {

    /**
     * A tool/technology mastered by the candidate with its numeric proficiency level.
     */
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record ToolProficiency(String tool, Integer level) {
    }

    /**
     * A spoken language with its level.
     */
    @JsonIgnoreProperties(ignoreUnknown = true)
    public record LanguageProficiency(String language, String level) {
    }
}
