package com.sijo.mcpboondmanager.dto.boond;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

@JsonIgnoreProperties(ignoreUnknown = true)
public record BoondTechnicalDocumentAttributes(
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