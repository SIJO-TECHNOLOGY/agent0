package com.sijo.mcpboondmanager.service;

import com.sijo.mcpboondmanager.client.BoondManagerClient;
import com.sijo.mcpboondmanager.dto.boond.BoondDictionaryEnvelope;
import com.sijo.mcpboondmanager.dto.boond.BoondDictionarySetting;
import com.sijo.mcpboondmanager.dto.dictionary.DictionaryEntryDto;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.stereotype.Component;

import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;

/**
 * Resolves a candidate's raw {@code availability} value (from the {@code /candidates} search list) into
 * a human-readable {@link String}.
 *
 * <p>BoondManager's {@code availability} field is polymorphic:
 * <ul>
 *   <li>a {@code setting.availability} dictionary id ({@code 0}-{@code 5}) for a relative band
 *       (e.g. {@code 0} → "Immédiate", {@code 3} → "3 mois") — resolved here to its dictionary label;</li>
 *   <li>the sentinel id {@code -1} meaning "availability not specified" — resolved to {@code null};</li>
 *   <li>a bare {@code yyyy-MM-dd} date for candidates available from a specific (future) date — returned
 *       verbatim as the formatted date string.</li>
 * </ul>
 *
 * <p>The label mapping is never hardcoded: the availability dictionary is reference data that rarely
 * changes, so it is fetched once via the {@code /application/dictionary} endpoint and memoized for the
 * lifetime of the application. If the dictionary cannot be loaded, resolution degrades gracefully to
 * {@code null} and the failure is logged; the lookup is retried on the next call rather than caching the
 * failure (mirrors {@link ExperienceDictionaryResolver}).
 */
@Component
public class AvailabilityDictionaryResolver {

    private static final Logger log = LoggerFactory.getLogger(AvailabilityDictionaryResolver.class);

    private static final ParameterizedTypeReference<BoondDictionaryEnvelope> DICTIONARY_TYPE =
            new ParameterizedTypeReference<>() {};

    /** BoondManager's sentinel id for "availability not specified". */
    private static final String NOT_SPECIFIED_ID = "-1";

    /** A candidate available from a specific date carries a bare {@code yyyy-MM-dd} value. */
    private static final Pattern DATE_PATTERN = Pattern.compile("\\d{4}-\\d{2}-\\d{2}");

    private final BoondManagerClient client;

    private volatile Map<String, String> cache;

    public AvailabilityDictionaryResolver(BoondManagerClient client) {
        this.client = client;
    }

    /**
     * @param rawAvailability the raw availability value ({@code setting.availability} id as text, the
     *                        {@code -1} sentinel, or a {@code yyyy-MM-dd} date); may be {@code null}
     * @return the formatted date for a date-based availability, the dictionary label for a known id, or
     *         {@code null} for {@code -1}/{@code null}/blank, an unknown id, or when the dictionary is
     *         unavailable
     */
    public String resolve(String rawAvailability) {
        if (rawAvailability == null || rawAvailability.isBlank()) {
            return null;
        }
        String value = rawAvailability.trim();
        if (DATE_PATTERN.matcher(value).matches()) {
            return value;
        }
        if (NOT_SPECIFIED_ID.equals(value)) {
            return null;
        }
        Map<String, String> resolved = ensureCache();
        if (resolved == null) {
            return null;
        }
        return resolved.get(value);
    }

    private Map<String, String> ensureCache() {
        Map<String, String> local = cache;
        if (local != null) {
            return local;
        }
        synchronized (this) {
            if (cache != null) {
                return cache;
            }
            Map<String, String> built = loadAvailabilityDictionary();
            if (built != null) {
                cache = built;
            }
            return built;
        }
    }

    private Map<String, String> loadAvailabilityDictionary() {
        try {
            BoondDictionaryEnvelope envelope = client.get(
                    BoondManagerCandidateService.DICTIONARY_PATH, DICTIONARY_TYPE);
            List<DictionaryEntryDto> entries = availabilityEntries(envelope);
            Map<String, String> built = new HashMap<>();
            for (DictionaryEntryDto entry : entries) {
                if (entry == null || entry.id() == null) {
                    continue;
                }
                built.put(entry.id(), entry.label());
            }
            return Map.copyOf(built);
        } catch (RuntimeException ex) {
            log.warn("Unable to load BoondManager availability dictionary; availability will be reported "
                    + "as not specified until it becomes available", ex);
            return null;
        }
    }

    private static List<DictionaryEntryDto> availabilityEntries(BoondDictionaryEnvelope envelope) {
        if (envelope == null || envelope.data() == null) {
            return List.of();
        }
        BoondDictionarySetting setting = envelope.data().setting();
        if (setting == null || setting.availability() == null) {
            return List.of();
        }
        return setting.availability();
    }
}