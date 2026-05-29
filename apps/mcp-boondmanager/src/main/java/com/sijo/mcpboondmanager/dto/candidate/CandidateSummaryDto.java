package com.sijo.mcpboondmanager.dto.candidate;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

@JsonIgnoreProperties(ignoreUnknown = true)
public record CandidateSummaryDto(
        Integer id,
        String firstName,
        String lastName,
        String email,
        Integer state,
        Integer availabilityType,
        String availabilityDate,
        Integer contractType,
        String mobilityArea,
        String city,
        String country,
        Double minSalary,
        Double maxSalary,
        Double minTjm,
        Double maxTjm,
        TechnicalDocumentSummaryDto technicalDocument
) {
}