package com.sijo.mcpboondmanager.dto.boond;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

/**
 * Attributes returned under {@code data.attributes} by
 * {@code GET /candidates/{id}/administrative}.
 *
 * <p>Known fields:
 * <ul>
 *   <li>{@code currentSalary} / {@code actualSalary} — current gross annual salary</li>
 *   <li>{@code minSalary} / {@code desiredSalary.min} — minimum desired salary</li>
 *   <li>{@code maxSalary} / {@code desiredSalary.max} — maximum desired salary</li>
 *   <li>{@code currentDailyRate} / {@code actualAverageDailyCost} — current TJM</li>
 *   <li>{@code minDailyRate} / {@code desiredAverageDailyCost.min} — minimum desired TJM</li>
 *   <li>{@code maxDailyRate} / {@code desiredAverageDailyCost.max} — maximum desired TJM</li>
 *   <li>{@code desiredContract} — desired contract type id (resolves via setting.typeOf.contract)</li>
 * </ul>
 */
@JsonIgnoreProperties(ignoreUnknown = true)
public record BoondCandidateAdministrativeAttributes(
        Double currentSalary,
        Double minSalary,
        Double maxSalary,
        Double currentDailyRate,
        Double minDailyRate,
        Double maxDailyRate,
        String currency,
        String administrativeComment,
        Integer typeOf,
        Integer desiredContract
) {
}
