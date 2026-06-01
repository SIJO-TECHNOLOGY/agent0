package com.sijo.mcpboondmanager.dto.candidate;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

import java.util.List;

@JsonIgnoreProperties(ignoreUnknown = true)
public record CandidateSummaryDto(
        Integer id,
        String firstName,
        String lastName,
        String email,
        Integer state,
        String availability,
        Integer contractType,
        List<String> mobilityAreas,
        String city,
        String country,
        String title,
        Integer experience,
        String skills,
        List<String> diplomas,
        List<String> expertiseAreas,
        List<String> activityAreas,
        List<TechnicalDocumentDto.ToolProficiency> tools,
        List<TechnicalDocumentDto.LanguageProficiency> languages
) {
}
