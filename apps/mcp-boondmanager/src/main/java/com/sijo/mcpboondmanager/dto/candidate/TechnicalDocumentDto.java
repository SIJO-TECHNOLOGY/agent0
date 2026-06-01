package com.sijo.mcpboondmanager.dto.candidate;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

import java.util.List;

@JsonIgnoreProperties(ignoreUnknown = true)
public record TechnicalDocumentDto(
        Integer id,
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
        Boolean isReferent,
        String updateDate
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
