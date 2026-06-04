package com.sijo.mcpboondmanager.dto.boond;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

/**
 * Attributes returned under {@code data.attributes} by
 * {@code GET /candidates/{id}/administrative}.
 *
 * <p>This endpoint exposes salary and daily-rate (TJM) expectations that are absent
 * from the {@code /information} endpoint. Field names follow BoondManager exactly.
 *
 * <p>Known salary fields (database names in parentheses):
 * <ul>
 *   <li>{@code currentSalary} (PARAM_TARIF1) — current gross annual salary</li>
 *   <li>{@code minSalary}     (PARAM_TARIF2) — minimum desired salary</li>
 *   <li>{@code maxSalary}     (PARAM_TARIF3) — maximum desired salary</li>
 * </ul>
 *
 * <p>Known daily-rate (TJM/CJM) fields:
 * <ul>
 *   <li>{@code currentDailyRate} (PARAM_CJM_ACTUAL) — actual current daily rate</li>
 *   <li>{@code minDailyRate}     (PARAM_CJM_MIN)    — minimum desired daily rate</li>
 *   <li>{@code maxDailyRate}     (PARAM_CJM_MAX)    — maximum desired daily rate</li>
 * </ul>
 *
 * <p>All numeric values are doubles (BoondManager stores them as DECIMAL(30,10)).
 * Fields absent from the response or set to 0 are mapped to {@code null} by the
 * service layer so the frontend never displays "0" as a valid rate.
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
        String administrativeComment
) {
}
