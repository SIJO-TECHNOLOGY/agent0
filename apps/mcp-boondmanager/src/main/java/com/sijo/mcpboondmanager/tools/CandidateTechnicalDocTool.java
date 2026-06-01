package com.sijo.mcpboondmanager.tools;

import com.sijo.mcpboondmanager.dto.candidate.TechnicalDocumentDto;
import com.sijo.mcpboondmanager.service.BoondManagerCandidateService;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Component;

@Component
public class CandidateTechnicalDocTool {

    private final BoondManagerCandidateService candidateService;

    public CandidateTechnicalDocTool(BoondManagerCandidateService candidateService) {
        this.candidateService = candidateService;
    }

    @Tool(
            name = "getCandidateTechnicalDocument",
            description = "Retrieves the technical document (skills profile / CV) of a candidate, " +
                    "resolved directly from the candidate id. Contains the document title, a free-text " +
                    "skills description, experience level, training/diploma level, the list of " +
                    "diplomas, expertise domains, activity sectors, tools with their proficiency " +
                    "level, spoken languages with their level, and a summary. The 'id' field is the " +
                    "candidate id and 'tdId' is the technical document's own identifier. This is the " +
                    "richest source of information for assessing a candidate's technical fit for a " +
                    "position. Call this after getCandidateDetail when a deep skills analysis is needed."
    )
    public TechnicalDocumentDto getCandidateTechnicalDocument(
            @ToolParam(description =
                    "Unique BoondManager candidate identifier (NOT the technical document id). " +
                    "Obtained from the 'id' field in searchCandidates results or getCandidateDetail.")
            Integer candidateId
    ) {
        return candidateService.getCandidateTechnicalDocument(candidateId);
    }
}