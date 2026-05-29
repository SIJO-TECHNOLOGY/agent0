package com.sijo.mcpboondmanager.tools;

import com.sijo.mcpboondmanager.dto.dictionary.DictionaryResponseDto;
import com.sijo.mcpboondmanager.service.BoondManagerCandidateService;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.stereotype.Component;

@Component
public class BoondDictionaryTool {

    private final BoondManagerCandidateService candidateService;

    public BoondDictionaryTool(BoondManagerCandidateService candidateService) {
        this.candidateService = candidateService;
    }

    @Tool(
            name = "getDictionary",
            description = "Retrieves all BoondManager reference data and enumeration values used as " +
                    "filter IDs in other tools. Returns diploma levels (Bac+2, Bac+3, Bac+5), " +
                    "contract types (CDI, CDD, Freelance), availability types, experience levels, " +
                    "expertise areas, activity sectors, tools, languages and candidate states. " +
                    "Must be called before searchCandidates when the user provides human-readable " +
                    "values that need to be resolved to their BoondManager IDs."
    )
    public DictionaryResponseDto getDictionary() {
        return candidateService.getDictionary();
    }
}