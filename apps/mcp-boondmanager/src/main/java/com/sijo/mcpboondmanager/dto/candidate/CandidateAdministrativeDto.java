package com.sijo.mcpboondmanager.dto.candidate;

/**
 * Normalized administrative data for a BoondManager candidate.
 *
 * <p>Exposes salary and daily-rate (TJM) expectations retrieved from
 * {@code GET /candidates/{id}/administrative}. All fields are nullable:
 * a {@code null} value means BoondManager returned 0 or the field was absent.
 *
 * @param candidateId       BoondManager candidate identifier.
 * @param currentSalary     Current gross annual salary.
 * @param minSalary         Minimum desired annual salary.
 * @param maxSalary         Maximum desired annual salary.
 * @param currentDailyRate  Actual current daily rate (TJM).
 * @param minDailyRate      Minimum desired daily rate.
 * @param maxDailyRate      Maximum desired daily rate.
 * @param currency          Currency code when provided (e.g. "EUR").
 */
public record CandidateAdministrativeDto(
        Integer candidateId,
        Double currentSalary,
        Double minSalary,
        Double maxSalary,
        Double currentDailyRate,
        Double minDailyRate,
        Double maxDailyRate,
        String currency
) {
}
