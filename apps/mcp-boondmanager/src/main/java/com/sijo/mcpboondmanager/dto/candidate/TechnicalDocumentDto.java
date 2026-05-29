package com.sijo.mcpboondmanager.dto.candidate;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

@JsonIgnoreProperties(ignoreUnknown = true)
public record TechnicalDocumentDto(
        Integer id,
        String title,
        String description,
        String summary,
        Integer experience,
        String training,
        String diplomas,
        String skills,
        String expertiseAreas,
        String activityAreas,
        String tools,
        String languages,
        Boolean isReferent,
        String creationDate,
        String updateDate,
        Integer candidateId
) {
}