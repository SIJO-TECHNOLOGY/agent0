package com.sijo.mcpboondmanager.tools;

import com.sijo.mcpboondmanager.dto.candidate.TechnicalDocumentDto;
import com.sijo.mcpboondmanager.service.BoondManagerCandidateService;
import org.jspecify.annotations.Nullable;
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
            description = """
                    Retrieves the technical document (skills profile / CV) of a candidate, resolved \
                    directly from the candidate id (GET /candidates/{id}/technical-data). This is the \
                    richest source of information for assessing a candidate's technical fit.

                    Returns:
                    - Identity: id (the candidate id), tdId (the technical document's own id), \
                    tdLink (optional external document link)
                    - Descriptive: title, description, summary
                    - Experience: experience (raw level id), experienceMinYears, \
                    experienceOpenEnded, experienceSpecified (language-neutral resolution), \
                    experienceLabelRaw (localized label, debug only)
                    - Education: training (training/diploma level), diplomas
                    - Skills: skills (raw free-text block; gated by includeRawSkillsText), \
                    expertiseAreas, activityAreas, tools (with proficiency level), languages (with \
                    level)
                    - Work history: references — the candidate's detailed assignment history (title, \
                    company, location, work period, free-text skills and description), never \
                    flattened or truncated; together with skills it is the strongest matching signal

                    Call this after getCandidateDetail when a deep skills analysis is needed. Call \
                    order: getDictionary -> searchCandidates -> getCandidateDetail -> \
                    getCandidateTechnicalDocument.""")
    public TechnicalDocumentDto getCandidateTechnicalDocument(
            @ToolParam(description =
                    "Unique BoondManager candidate identifier (NOT the technical document id). " +
                    "Obtained from the 'id' field in searchCandidates results or getCandidateDetail.")
            Integer candidateId,
            @ToolParam(required = false, description = """
                    When true, includes the raw skills free-text block in addition to the structured \
                    fields. Useful when the structured fields (tools, languages, expertiseAreas, \
                    references) alone are insufficient for deep skills analysis. Default: true.""")
            @Nullable Boolean includeRawSkillsText
    ) {
        TechnicalDocumentDto document = candidateService.getCandidateTechnicalDocument(candidateId);
        if (Boolean.FALSE.equals(includeRawSkillsText)) {
            return withoutRawSkillsText(document);
        }
        return document;
    }

    /**
     * Returns a copy of the document with the raw {@code skills} free-text block removed. Pure
     * projection — the structured fields (tools, languages, expertise/activity areas, references)
     * are preserved.
     */
    private static TechnicalDocumentDto withoutRawSkillsText(TechnicalDocumentDto d) {
        return new TechnicalDocumentDto(
                d.id(),
                d.tdId(),
                d.tdLink(),
                d.title(),
                d.description(),
                d.summary(),
                d.experience(),
                d.experienceMinYears(),
                d.experienceOpenEnded(),
                d.experienceSpecified(),
                d.experienceLabelRaw(),
                d.training(),
                d.diplomas(),
                null,                  // raw skills text omitted when includeRawSkillsText=false
                d.expertiseAreas(),
                d.activityAreas(),
                d.tools(),
                d.languages(),
                d.references()
        );
    }
}