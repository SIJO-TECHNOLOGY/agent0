package com.sijo.mcpboondmanager.tools;

import com.sijo.mcpboondmanager.dto.dictionary.DictionaryResponseDto;
import com.sijo.mcpboondmanager.service.BoondManagerCandidateService;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Component;

@Component
public class BoondDictionaryTool {

    private final BoondManagerCandidateService candidateService;

    public BoondDictionaryTool(BoondManagerCandidateService candidateService) {
        this.candidateService = candidateService;
    }

    @Tool(
            name = "getDictionary",
            description = """
                    Retrieves all BoondManager reference data and enumeration values used as filter \
                    IDs in the other tools. Must be called before searchCandidates when the user \
                    provides human-readable values that need to be resolved to their BoondManager IDs.

                    Returns setting.* dictionaries (each entry has an id + label):
                    - state.candidate: candidate pipeline states (the candidateStates filter)
                    - typeOf.contract: contract types e.g. CDI, CDD, Freelance (the contractTypes \
                    filter)
                    - typeOf.resource: candidate types (the candidateTypes filter)
                    - availability: availability types (the availabilityTypes filter)
                    - mobilityArea: mobility zones, with nested option ids (the mobilityAreas filter)
                    - experience: experience levels (the experiences filter)
                    - training: training / diploma levels e.g. Bac+2, Bac+3, Bac+5
                    - expertiseArea: expertise areas (the expertiseAreas filter)
                    - activityArea: activity sectors, with nested option ids (the activityAreas \
                    filter; top-level entries are group headings)
                    - tool: tools / technologies (the tools filter)
                    - languageSpoken and languageLevel: spoken languages and proficiency levels \
                    (combined as "<spokenId>|<levelId>" for the languages filter)
                    - evaluation: evaluation scores (the evaluations filter)
                    - source: sourcing origins (the sources filter)

                    Call order: getDictionary -> searchCandidates -> getCandidateDetail -> \
                    getCandidateTechnicalDocument.""")
    public DictionaryResponseDto getDictionary(
            @ToolParam(required = false, description =
                    "Optional BoondManager locale for the returned labels (e.g. 'en', 'fr'). " +
                            "When omitted, the account's default language is used.")
            String language
    ) {
        return candidateService.getDictionary(language);
    }
}