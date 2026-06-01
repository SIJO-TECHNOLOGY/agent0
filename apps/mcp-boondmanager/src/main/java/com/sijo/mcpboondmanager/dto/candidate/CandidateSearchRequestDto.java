package com.sijo.mcpboondmanager.dto.candidate;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;

import java.util.List;

/**
 * Query parameters for the BoondManager {@code /candidates} search endpoint, restricted to the
 * filters relevant to recruitment and sourcing.
 *
 * <p>Repeatable filters are modeled as lists; the service serializes each element as a separate
 * {@code name[]=value} query parameter (BoondManager unions multiple values). Scalar filters are
 * serialized as plain {@code name=value}. All fields are optional; null fields and empty lists are
 * never sent.
 */
public record CandidateSearchRequestDto(
        String keywords,
        String keywordsType,
        List<Integer> candidateStates,
        List<Integer> candidateTypes,
        List<Integer> availabilityTypes,
        List<Integer> contractTypes,
        List<Integer> experiences,
        List<String> expertiseAreas,
        List<String> activityAreas,
        String mobilityAreas,
        List<String> languages,
        List<String> tools,
        List<String> evaluations,
        List<String> sources,
        List<String> shields,
        String location,
        String coordinates,
        @Min(5)
        @Max(200)
        Integer geoDistance,
        String period,
        String startDate,
        String endDate,
        String periodDynamic,
        @Min(1)
        Integer page,
        @Min(1)
        @Max(500)
        Integer maxResults,
        List<String> sort,
        String order,
        List<String> columns
) {
}
