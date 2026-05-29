package com.sijo.mcpboondmanager.dto.boond;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

@JsonIgnoreProperties(ignoreUnknown = true)
public record BoondTechnicalDocumentSummaryAttributes(
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