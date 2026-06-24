package com.sijo.mcpboondmanager.dto.candidate;

/**
 * Normalized administrative data for a BoondManager candidate.
 *
 * @param candidateId      BoondManager candidate identifier.
 * @param currentSalary    Current gross annual salary.
 * @param minSalary        Minimum desired annual salary.
 * @param maxSalary        Maximum desired annual salary.
 * @param currentDailyRate Actual current daily rate (TJM).
 * @param minDailyRate     Minimum desired daily rate.
 * @param maxDailyRate     Maximum desired daily rate.
 * @param currency         Currency code when provided.
 * @param contractType     Desired contract type id from {@code desiredContract} field
 *                         (resolves via setting.typeOf.contract dictionary).
 */
public record CandidateAdministrativeDto(
        Integer candidateId,
        Double currentSalary,
        Double minSalary,
        Double maxSalary,
        Double currentDailyRate,
        Double minDailyRate,
        Double maxDailyRate,
        String currency,
        Integer contractType
) {
}
