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

/**
 * Resolves a raw BoondManager experience id (from {@code setting.experience}) into a language-neutral
 * {@link ResolvedExperience}, by parsing the dictionary label rather than hardcoding ids (which are
 * non-sequential and tenant-configurable).
 *
 * <p>The experience dictionary is reference data that rarely changes, so it is fetched once via the
 * {@code /application/dictionary} endpoint and memoized for the lifetime of the application. If the
 * dictionary cannot be loaded, resolution degrades gracefully to {@link ResolvedExperience#UNSPECIFIED}
 * (the raw id is still returned by the tools) and the failure is logged; the lookup is retried on the next
 * call rather than caching the failure.
 */
@Component
public class ExperienceDictionaryResolver {

    private static final Logger log = LoggerFactory.getLogger(ExperienceDictionaryResolver.class);

    private static final ParameterizedTypeReference<BoondDictionaryEnvelope> DICTIONARY_TYPE =
            new ParameterizedTypeReference<>() {};

    /** BoondManager's sentinel id for "experience not specified". */
    private static final int NOT_SPECIFIED_ID = -1;

    private final BoondManagerClient client;

    private volatile Map<String, ResolvedExperience> cache;

    public ExperienceDictionaryResolver(BoondManagerClient client) {
        this.client = client;
    }

    /**
     * @param experienceId the raw experience id ({@code setting.experience}); may be {@code null}
     * @return the resolved experience, or {@link ResolvedExperience#UNSPECIFIED} for {@code -1}, {@code null},
     *         an unknown id, or when the dictionary is unavailable
     */
    public ResolvedExperience resolve(Integer experienceId) {
        if (experienceId == null || experienceId == NOT_SPECIFIED_ID) {
            return ResolvedExperience.UNSPECIFIED;
        }
        Map<String, ResolvedExperience> resolved = ensureCache();
        if (resolved == null) {
            return ResolvedExperience.UNSPECIFIED;
        }
        return resolved.getOrDefault(String.valueOf(experienceId), ResolvedExperience.UNSPECIFIED);
    }

    private Map<String, ResolvedExperience> ensureCache() {
        Map<String, ResolvedExperience> local = cache;
        if (local != null) {
            return local;
        }
        synchronized (this) {
            if (cache != null) {
                return cache;
            }
            Map<String, ResolvedExperience> built = loadExperienceDictionary();
            if (built != null) {
                cache = built;
            }
            return built;
        }
    }

    private Map<String, ResolvedExperience> loadExperienceDictionary() {
        try {
            BoondDictionaryEnvelope envelope = client.get(
                    BoondManagerCandidateService.DICTIONARY_PATH, DICTIONARY_TYPE);
            List<DictionaryEntryDto> entries = experienceEntries(envelope);
            Map<String, ResolvedExperience> built = new HashMap<>();
            for (DictionaryEntryDto entry : entries) {
                if (entry == null || entry.id() == null) {
                    continue;
                }
                ExperienceLabelParser.ParsedLabel parsed = ExperienceLabelParser.parse(entry.label());
                built.put(entry.id(), new ResolvedExperience(
                        parsed.minYears(), parsed.openEnded(), true, entry.label()));
            }
            return Map.copyOf(built);
        } catch (RuntimeException ex) {
            log.warn("Unable to load BoondManager experience dictionary; experience fields will be "
                    + "reported as not specified until it becomes available", ex);
            return null;
        }
    }

    private static List<DictionaryEntryDto> experienceEntries(BoondDictionaryEnvelope envelope) {
        if (envelope == null || envelope.data() == null) {
            return List.of();
        }
        BoondDictionarySetting setting = envelope.data().setting();
        if (setting == null || setting.experience() == null) {
            return List.of();
        }
        return setting.experience();
    }
}
