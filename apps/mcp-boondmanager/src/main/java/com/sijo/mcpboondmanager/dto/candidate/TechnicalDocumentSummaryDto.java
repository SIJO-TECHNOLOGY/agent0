package com.sijo.mcpboondmanager.dto.candidate;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

@JsonIgnoreProperties(ignoreUnknown = true)
public record TechnicalDocumentSummaryDto(
        String title,
        Integer experience,
        String training,
        String diplomas,
        String skills,
        String expertiseAreas,
        String activityAreas,
        String tools,
        String languages
) {
}