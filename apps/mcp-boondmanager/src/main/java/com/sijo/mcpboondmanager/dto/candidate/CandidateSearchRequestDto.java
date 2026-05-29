package com.sijo.mcpboondmanager.dto.candidate;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;

public record CandidateSearchRequestDto(
        String keywords,
        Integer state,
        Integer availabilityType,
        String availabilityDate,
        Integer contractType,
        Integer experience,
        String training,
        String expertiseAreas,
        String activityAreas,
        String mobilityArea,
        Double minSalary,
        Double maxSalary,
        Double minTjm,
        Double maxTjm,
        @Min(1)
        Integer page,
        @Min(1)
        @Max(100)
        Integer numberPerPage
) {
}
