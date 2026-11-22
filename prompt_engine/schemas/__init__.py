"""Structured output schemas. SCHEMAS maps template `schema:` names to models."""
from prompt_engine.schemas.analysis import DocumentAnalysis, LearningObjectives, TeachingStrategy, TopicMap
from prompt_engine.schemas.evaluation import ExperimentJudgement, NotesEvaluation, NotesRefinement
from prompt_engine.schemas.resources import DiagramSet, ExampleSet, FlashcardSet, LectureNotes, QuestionSet, Quiz, RevisionNotes

SCHEMAS = {m.__name__: m for m in (
    DocumentAnalysis, TopicMap, LearningObjectives, TeachingStrategy, LectureNotes, ExampleSet, QuestionSet,
    RevisionNotes, FlashcardSet, DiagramSet, Quiz, NotesEvaluation, NotesRefinement, ExperimentJudgement,
)}
