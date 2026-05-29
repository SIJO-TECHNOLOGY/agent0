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
            description = "Retrieves the technical document (skills profile / CV) of a candidate. " +
                    "Contains the detailed skills text, expertise domains, activity sectors, " +
                    "diploma list, experience level, tools with proficiency levels (1-5), spoken " +
                    "languages with levels, and a summary. This is the richest source of " +
                    "information for assessing a candidate's technical fit for a position. Call " +
                    "this after getCandidateDetail when a deep skills analysis is needed."
    )
    public TechnicalDocumentDto getCandidateTechnicalDocument(
            @ToolParam(description =
                    "Unique BoondManager candidate identifier. Obtained from the 'id' field in " +
                    "searchCandidates results or getCandidateDetail.")
            Integer candidateId
    ) {
        return candidateService.getCandidateTechnicalDocument(candidateId);
    }
}