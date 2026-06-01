package com.sijo.mcpboondmanager.tools;

import com.sijo.mcpboondmanager.dto.candidate.CandidateSearchRequestDto;
import com.sijo.mcpboondmanager.dto.candidate.CandidateSearchResponseDto;
import com.sijo.mcpboondmanager.service.BoondManagerCandidateService;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Component;

import java.util.List;

@Component
public class CandidateSearchTool {

    private final BoondManagerCandidateService candidateService;

    public CandidateSearchTool(BoondManagerCandidateService candidateService) {
        this.candidateService = candidateService;
    }

    @Tool(
            name = "searchCandidates",
            description = "Searches candidates in BoondManager with rich, optional filters and returns " +
                    "a paginated list of candidate profiles. Use getDictionary first to resolve " +
                    "human-readable values (states, contract types, mobility zones, expertise areas, " +
                    "tools, languages, ...) to their BoondManager IDs before calling this tool. " +
                    "Supports full-text keyword search with a configurable keywordsType, multi-value " +
                    "reference filters (repeatable parameters whose values are unioned), geographic " +
                    "search (location or coordinates together with geoDistance), date-range filtering " +
                    "(period with startDate/endDate, or periodDynamic), pagination (page, maxResults up " +
                    "to 500), sorting (sort + order) and response field selection (columns). Returns " +
                    "candidate summaries; call getCandidateDetail for a full profile and " +
                    "getCandidateTechnicalDocument for the skills/CV. Call order: getDictionary -> " +
                    "searchCandidates -> getCandidateDetail -> getCandidateTechnicalDocument."
    )
    public CandidateSearchResponseDto searchCandidates(
            @ToolParam(required = false, description =
                    "Full-text search query. Operators: +term forces inclusion, \"exact phrase\" for " +
                    "exact match. The field(s) searched are controlled by keywordsType.")
            String keywords,
            @ToolParam(required = false, description =
                    "Which field the keywords search targets. One of: resumeTd (default; resume + " +
                    "technical document), lastName, firstName, fullName, strictFullName, emails, " +
                    "title, titleSkills, phones, resume, td.")
            String keywordsType,
            @ToolParam(required = false, description =
                    "Candidate pipeline state IDs (repeatable; values are unioned). " +
                    "From getDictionary: setting.state.candidate.")
            List<Integer> candidateStates,
            @ToolParam(required = false, description =
                    "Candidate type IDs (repeatable). From getDictionary: setting.typeOf.resource.")
            List<Integer> candidateTypes,
            @ToolParam(required = false, description =
                    "Availability type IDs (repeatable). From getDictionary: setting.availability.")
            List<Integer> availabilityTypes,
            @ToolParam(required = false, description =
                    "Desired contract type IDs (repeatable). From getDictionary: setting.typeOf.contract.")
            List<Integer> contractTypes,
            @ToolParam(required = false, description =
                    "Experience level IDs (repeatable). From getDictionary: setting.experience.")
            List<Integer> experiences,
            @ToolParam(required = false, description =
                    "Expertise area IDs (repeatable). From getDictionary: setting.expertiseArea.")
            List<String> expertiseAreas,
            @ToolParam(required = false, description =
                    "Activity sector IDs (repeatable). From getDictionary: the nested option IDs under " +
                    "setting.activityArea[].option (the top-level setting.activityArea entries are " +
                    "group headings, not selectable IDs).")
            List<String> activityAreas,
            @ToolParam(required = false, description =
                    "Mobility zone ID. From getDictionary: the nested option IDs under " +
                    "setting.mobilityArea[].option (the top-level entries are group headings).")
            String mobilityAreas,
            @ToolParam(required = false, description =
                    "Spoken-language filters (repeatable), each formatted \"<spokenId>|<levelId>\". " +
                    "From getDictionary: setting.languageSpoken (spokenId) and setting.languageLevel " +
                    "(levelId). Example: \"anglais|courant\".")
            List<String> languages,
            @ToolParam(required = false, description =
                    "Tool/technology IDs (repeatable). From getDictionary: setting.tool. Add the " +
                    "literal \"#AND#\" as the FIRST element to require ALL listed tools; otherwise " +
                    "ANY of them matches.")
            List<String> tools,
            @ToolParam(required = false, description =
                    "Evaluation score IDs (repeatable). From getDictionary: setting.evaluation.")
            List<String> evaluations,
            @ToolParam(required = false, description =
                    "Sourcing origin IDs (repeatable). From getDictionary: setting.source.")
            List<String> sources,
            @ToolParam(required = false, description =
                    "Profile completeness filter (repeatable). One or more of: uncomplete, minimum, " +
                    "complete.")
            List<String> shields,
            @ToolParam(required = false, description =
                    "Free-text address to geocode for a geographic search (e.g. \"Paris\"). " +
                    "Requires geoDistance.")
            String location,
            @ToolParam(required = false, description =
                    "Geographic point as \"latitude,longitude\" (e.g. \"48.8566,2.3522\"). " +
                    "Requires geoDistance. Alternative to location.")
            String coordinates,
            @ToolParam(required = false, description =
                    "Search radius in kilometers (5-200). Required when using location or coordinates.")
            Integer geoDistance,
            @ToolParam(required = false, description =
                    "Date field to filter on, used together with startDate/endDate. One of: created, " +
                    "available, updated, noAction, withActions.")
            String period,
            @ToolParam(required = false, description =
                    "Start of the period range, ISO date yyyy-MM-dd. Used with period.")
            String startDate,
            @ToolParam(required = false, description =
                    "End of the period range, ISO date yyyy-MM-dd. Used with period.")
            String endDate,
            @ToolParam(required = false, description =
                    "Relative period preset instead of startDate/endDate. Examples: thisMonth, " +
                    "lastMonth, nextMonth, thisYear.")
            String periodDynamic,
            @ToolParam(required = false, description =
                    "Page number (1-based). Default: 1.")
            Integer page,
            @ToolParam(required = false, description =
                    "Results per page (1-500). Default: 30.")
            Integer maxResults,
            @ToolParam(required = false, description =
                    "Sort field(s), repeatable. One or more of: lastName, firstName, title, " +
                    "availability, availabilityType, numberOfActivePositionings, mainManager.lastName, " +
                    "updateDate, state, experience, creationDate, evaluation, hrManager.lastName, " +
                    "source, distance.")
            List<String> sort,
            @ToolParam(required = false, description =
                    "Sort direction: asc or desc.")
            String order,
            @ToolParam(required = false, description =
                    "Which fields the API should include in each candidate of the response " +
                    "(repeatable). One or more of: name, title, state, activePositionings, " +
                    "availability, mobilityAreas, details, updated, mainManager, resume, hrManager, " +
                    "expertiseAreas, creationDate, lastActionDate, source, diplomas, activityAreas, " +
                    "globalEvaluation, evaluations, experience, references, languages, tools.")
            List<String> columns
    ) {
        CandidateSearchRequestDto request = new CandidateSearchRequestDto(
                keywords,
                keywordsType,
                candidateStates,
                candidateTypes,
                availabilityTypes,
                contractTypes,
                experiences,
                expertiseAreas,
                activityAreas,
                mobilityAreas,
                languages,
                tools,
                evaluations,
                sources,
                shields,
                location,
                coordinates,
                geoDistance,
                period,
                startDate,
                endDate,
                periodDynamic,
                page,
                maxResults,
                sort,
                order,
                columns
        );
        return candidateService.searchCandidates(request);
    }
}
