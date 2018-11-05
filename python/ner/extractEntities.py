#!/usr/bin/python

import sys
import os
import re
import subprocess
import platform
import time
import codecs
from nltk.tokenize import sent_tokenize, word_tokenize
import csv
from signal import *
import pandas as pd
import argparse
import numpy as np\

BASE_DIR = 'twitter_nlp.jar'

if os.environ.has_key('TWITTER_NLP'):
    BASE_DIR = os.environ['TWITTER_NLP']

sys.path.append('%s/python' % (BASE_DIR))
sys.path.append('%s/python/ner' % (BASE_DIR))
sys.path.append('%s/hbc/python' % (BASE_DIR))

import Features
import twokenize
from LdaFeatures import LdaFeatures
from Dictionaries import Dictionaries
from Vocab import Vocab

sys.path.append('%s/python/cap' % (BASE_DIR))
sys.path.append('%s/python' % (BASE_DIR))
import cap_classifier
import pos_tagger_stdin
import chunk_tagger_stdin
import event_tagger_stdin

reload(sys)  
sys.setdefaultencoding('utf-8')

def GetNer(ner_model, memory="256m"):
    return subprocess.Popen('java -Xmx%s -cp %s/mallet-2.0.6/lib/mallet-deps.jar:%s/mallet-2.0.6/class cc.mallet.fst.SimpleTaggerStdin --weights sparse --model-file %s/models/ner/%s' % (memory, BASE_DIR, BASE_DIR, BASE_DIR, ner_model),
                           shell=True,
                           close_fds=True,
                           stdin=subprocess.PIPE,
                           stdout=subprocess.PIPE)

def GetLLda():
    return subprocess.Popen('%s/hbc/models/LabeledLDA_infer_stdin.out %s/hbc/data/combined.docs.hbc %s/hbc/data/combined.z.hbc 100 100' % (BASE_DIR, BASE_DIR, BASE_DIR),
                           shell=True,
                           close_fds=True,
                           stdin=subprocess.PIPE,
                           stdout=subprocess.PIPE)

#if platform.architecture() != ('64bit', 'ELF'):
#    sys.exit("Requires 64 bit Linux")
def flatten(mylist, outlist,ignore_types=(str, bytes)):

    if mylist !=[]:
        for item in mylist:
            #print not isinstance(item, ne.NE_candidate)
            if isinstance(item, list) and not isinstance(item, ignore_types):
                flatten(item, outlist)
            else:
                item=item.strip(' \t\n\r')
                outlist.append(item)
    return outlist



parser = argparse.ArgumentParser()
parser.add_argument("input_file", help="Path to the input file. Each line should have the text.Optionally it can be a tab delimited file.")
parser.add_argument("--text-pos", "-t",help="Column number (starting from 0) of the column containing text", type=int, default=0)
parser.add_argument("--output-file", "-o", help="Path to the output file", default=None)
parser.add_argument("--chunk", "-k", action="store_true", default=False)
parser.add_argument("--pos", "-p", action="store_true", default=False)
parser.add_argument("--event", "-e", action="store_true", default=False)
parser.add_argument("--classify", "-c", action="store_true", default=False)
parser.add_argument("--mallet-memory", "-m", default="256m", help="Memory allocated for Mallet instance")
options = parser.parse_args()

print >> sys.stderr , "Starting with the following configuration\n", "--"*20
print >> sys.stderr , "Input file: %s" % options.input_file
print >> sys.stderr , "Text Position: %s" % options.text_pos
print >> sys.stderr , "Output file: %s" % options.output_file
print >> sys.stderr , "Chunk: %s" % options.chunk
print >> sys.stderr , "POS: %s" % options.pos
print >> sys.stderr , "Event: %s" % options.event
print >> sys.stderr , "Classify: %s" % options.classify
print >> sys.stderr , "Mallet Memory: %s" % options.mallet_memory
print >> sys.stderr , "--"*20

if options.input_file is None or options.input_file == "":
    print >> sys.stderr, "No input file given."
    print >> sys.stderr, parser.print_help()
    sys.exit(-1)

if options.output_file is None or options.input_file == "":
    print >> sys.stderr, "No output file given. Will write to STDOUT."

if options.pos:
    posTagger = pos_tagger_stdin.PosTagger()
else:
    posTagger = None

if options.chunk and options.pos:
    chunkTagger = chunk_tagger_stdin.ChunkTagger()
else:
    chunkTagger = None

if options.event and options.pos:
    eventTagger = event_tagger_stdin.EventTagger()
else:
    eventTagger = None

if options.classify:
    llda = GetLLda()
else:
    llda = None

if options.pos and options.chunk:
    ner_model = 'ner.model'
elif options.pos:
    ner_model = 'ner_nochunk.model'
else:
    ner_model = 'ner_nopos_nochunk.model'

ner = GetNer(ner_model, memory=options.mallet_memory)
fe = Features.FeatureExtractor('%s/data/dictionaries' % (BASE_DIR))

capClassifier = cap_classifier.CapClassifier()

vocab = Vocab('%s/hbc/data/vocab' % (BASE_DIR))

dictMap = {}
i = 1
for line in open('%s/hbc/data/dictionaries' % (BASE_DIR)):
    dictionary = line.rstrip('\n')
    dictMap[i] = dictionary
    i += 1

dict2index = {}
for i in dictMap.keys():
    dict2index[dictMap[i]] = i

if llda:
    dictionaries = Dictionaries('%s/data/LabeledLDA_dictionaries3' % (BASE_DIR), dict2index)
entityMap = {}
i = 0
if llda:
    for line in open('%s/hbc/data/entities' % (BASE_DIR)):
        entity = line.rstrip('\n')
        entityMap[entity] = i
        i += 1

dict2label = {}
for line in open('%s/hbc/data/dict-label3' % (BASE_DIR)):
    (dictionary, label) = line.rstrip('\n').split(' ')
    dict2label[dictionary] = label

print >> sys.stderr, "Finished loading all models. Now reading from %s and writing to %s"  % (options.input_file, options.output_file)
# WRITE TO STDOUT IF NO FILE IS GIVEN FOR OUTPUT
out_fp = open(options.output_file, "wb+") if options.output_file is not None else sys.stdout
writer = csv.writer(out_fp, delimiter=',')

# tweets=pd.read_csv("tweet_data_frame.csv", header=0, index_col = 'ID' ,encoding = 'utf-8',delimiter=',')
tweets=pd.read_csv(options.input_file, header=0, encoding = 'utf-8',delimiter=',')
#with open(options.input_file) as fp:
time_array=[]
batch_size=3000
for g, tweet_batch in tweets.groupby(np.arange(len(tweets)) //batch_size):
    nLines = 0
    start_time = time.time()
    for index, row in tweet_batch.iterrows():        
        #row = rows.strip().split("\t")
        tweet = (row['Output'])
        # print(tweet)
        tweetSentences=list(filter (lambda sentence: len(sentence)>1, tweet.split('\n')))
        tweetSentenceList_inter=flatten(list(map(lambda sentText: sent_tokenize(sentText.lstrip().rstrip()),tweetSentences)),[])
        tweetSentenceList=list(filter (lambda sentence: len(sentence)>1, tweetSentenceList_inter))
        nLines += len(tweetSentenceList)
        tweet=''.join(tweetSentenceList)
        line = tweet.encode('utf-8', "ignore")
        if not line:
            print >> sys.stderr, "Finished reading %s lines from %s"  % (nLines -1, options.input_file)
            break
        #print >> sys.stderr, "Read Line: %s, %s" % (nLines, line),
        words = twokenize.tokenize(line)
        seq_features = []
        tags = []

        goodCap = capClassifier.Classify(words) > 0.9

        if posTagger:
            pos = posTagger.TagSentence(words)
            #pos = [p.split(':')[0] for p in pos]  # remove weights   
            pos = [re.sub(r':[^:]*$', '', p) for p in pos]  # remove weights   
        else:
            pos = None

        # Chunking the tweet
        if posTagger and chunkTagger:
            word_pos = zip(words, [p.split(':')[0] for p in pos])
            chunk = chunkTagger.TagSentence(word_pos)
            chunk = [c.split(':')[0] for c in chunk]  # remove weights      
        else:
            chunk = None

        #Event tags
        if posTagger and eventTagger:
            events = eventTagger.TagSentence(words, [p.split(':')[0] for p in pos])
            events = [e.split(':')[0] for e in events]
        else:
            events = None

        quotes = Features.GetQuotes(words)
        for i in range(len(words)):
            features = fe.Extract(words, pos, chunk, i, goodCap) + ['DOMAIN=Twitter']
            if quotes[i]:
                features.append("QUOTED")
            seq_features.append(" ".join(features))
        ner.stdin.write(("\t".join(seq_features) + "\n").encode('utf8'))
            
        for i in range(len(words)):
            tags.append(ner.stdout.readline().rstrip('\n').strip(' '))

        features = LdaFeatures(words, tags)

        #Extract and classify entities
        for i in range(len(features.entities)):
            type = None
            wids = [str(vocab.GetID(x.lower())) for x in features.features[i] if vocab.HasWord(x.lower())]
            if llda and len(wids) > 0:
                entityid = "-1"
                if entityMap.has_key(features.entityStrings[i].lower()):
                    entityid = str(entityMap[features.entityStrings[i].lower()])
                labels = dictionaries.GetDictVector(features.entityStrings[i])

                if sum(labels) == 0:
                    labels = [1 for x in labels]
                llda.stdin.write("\t".join([entityid, " ".join(wids), " ".join([str(x) for x in labels])]) + "\n")
                sample = llda.stdout.readline().rstrip('\n')
                labels = [dict2label[dictMap[int(x)]] for x in sample[4:len(sample)-8].split(' ')]

                count = {}
                for label in labels:
                    count[label] = count.get(label, 0.0) + 1.0
                maxL = None
                maxP = 0.0
                for label in count.keys():
                    p = count[label] / float(len(count))
                    if p > maxP or maxL == None:
                        maxL = label
                        maxP = p

                if maxL != 'None':
                    tags[features.entities[i][0]] = "B-%s" % (maxL)
                    for j in range(features.entities[i][0]+1,features.entities[i][1]):
                        tags[j] = "I-%s" % (maxL)
                else:
                    tags[features.entities[i][0]] = "O"
                    for j in range(features.entities[i][0]+1,features.entities[i][1]):
                        tags[j] = "O"
            else:
                tags[features.entities[i][0]] = "B-ENTITY"
                for j in range(features.entities[i][0]+1,features.entities[i][1]):
                    tags[j] = "I-ENTITY"

        output = ["%s//%s" % (words[x], tags[x]) for x in range(len(words)) if tags[x] !="O"]
        if pos:
            output = ["%s//%s" % (output[x], pos[x]) for x in range(len(output))]
        if chunk:
            output = ["%s//%s" % (output[x], chunk[x]) for x in range(len(output))]
        if events:
            output = ["%s//%s" % (output[x], events[x]) for x in range(len(output))]
        mentions=""
        candidateMention=""
        for outputStr in output:
            #outputStr=output[index]
            candidate=" ".join((outputStr.split("//"))[:-1])
            tag=(outputStr.split("//"))[-1]
            #text="".join(candidate)
            if (tag=='B-ENTITY'):
                #print candidateMention
                mentions+=candidateMention+","
                candidateMention=candidate
            else:
                candidateMention+=" "+candidate
        mentions+=candidateMention
        #sys.stdout.write((" ".join(output) + "\n").encode('utf8'))
        #row[options.text_pos] = (" ".join(output)).encode('utf8')
        row[options.text_pos] = mentions.strip(',')
        writer.writerow(row)
            #print >> sys.stderr, "\tWrote Line: %s, %s" % (nLines, row[options.text_pos])

        #    if pos:
        #        sys.stdout.write((" ".join(["%s/%s/%s" % (words[x], tags[x], pos[x]) for x in range(len(words))]) + "\n").encode('utf8'))
        #    else:
        #        sys.stdout.write((" ".join(["%s/%s" % (words[x], tags[x]) for x in range(len(words))]) + "\n").encode('utf8'))        
            
            #sys.stdout.flush()

            #seems like there is a memory leak comming from mallet, so just restart it every 1,000 tweets or so
        if nLines % 10000 == 0:
            #start = time.time()
            ner.stdin.close()
            ner.stdout.close()
            #if ner.wait() != 0:
            #sys.stderr.write("error!\n")
            #ner.kill()
            os.kill(ner.pid, SIGTERM)       #Need to do this for python 2.4
            ner.wait()
            ner = GetNer(ner_model)
           

    end_time = time.time()
    processing_time= (str(end_time-start_time))
    #time_array.append(total_time)
    #print >> sys.stderr, "Average time per tweet = %ss" % processing_time
    list_to_convert=[(batch_size,nLines,processing_time)]
    time_holder=(pd.DataFrame.from_records(list_to_convert, columns=['batch_size','no_of_Sentences', 'pTime']))
    time_holder.to_csv('ritter_efficiency.csv',header=False,mode= 'a',encoding='utf-8')

