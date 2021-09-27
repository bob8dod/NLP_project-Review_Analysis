import json
import re
from urllib.request import urlopen
import requests
from bs4 import BeautifulSoup
from multiprocessing import Pool
from functools import partial
import time

import pandas as pd
import numpy as np

import django
django.setup()

from django.views.generic import ListView, TemplateView
from django.shortcuts import render, redirect
from .models import TweetModel, TweetComment, ProductKeyword #CommentKeyword
# Create your views here.
from django.contrib.auth.decorators import login_required

from eunjeon import Mecab
import gensim
from sklearn.metrics.pairwise import cosine_similarity

from collections import defaultdict


mecab = Mecab()
word2vec_model = gensim.models.Word2Vec.load('tweet/word2vec_by_mecab.model')
containers = ['NNG', 'NNP', 'NNB', 'NNBC', 'NR', 'NP', 'VV', 'VA', 'VX', 'VCP', 'VCN', 'MM']
stop_words = ['JKC', 'JKG', 'JKO', 'JKB', 'JKV', 'JKQ', 'JX', 'JC']
con = pd.read_csv("tweet/word_vector.csv", usecols=['0', 'total_value'])
word_index = set(con['0'].to_list())
con = np.array(con)
weights = np.load('tweet/weights.npy', allow_pickle=True)
hangul = re.compile('[^가-힣]+')

def positive_or_negative(arr):
    return 1 / (1 + np.exp(
        -1 * (np.dot([0 if h < 0 else h for h in np.dot(arr, weights[0]) + weights[1]], weights[2]) + weights[3])))
def DNN_func(sentence):
    after_preprocess = re.sub(r" {2,}", " ", hangul.sub(' ', sentence))
    tmp = [text[0] for text in mecab.pos(after_preprocess) if
           text[1][0] != 'E' and text[1][0] != 'S' and text[1][0] != 'X' and text[1][0] != 'J' and text[
               1] != 'UNKNOWN' and text[0] != '.']
    value = [float(con[con[:, 0] == word, 1]) if word in word_index else 0 for word in tmp]
    if len(value) >= 50:
        value = value[:50]
    else:
        value = np.pad(value, (0, 50 - len(value)), 'constant')

    consider_relu = [0 if h < 0 else 1 for h in np.dot(value, weights[0]) + weights[1]]
    arr = [*map(np.sum, [[h * weights[2][index] + weights[3] / (50 * 25) for index, h in enumerate(
        [0 if consider_relu[index] == 0 else value[i] * weights[0][i][index] + weights[1][index] / 50 for index in
         range(25)])] for i in range(50)])]

    before_text = sentence.split(' ')
    arr_num = 0
    values = []
    for before_mecab in before_text:
        value_tmp = 0
        for k in range(len(mecab.morphs(before_mecab))):
            if arr_num + k >= 50: break
            value_tmp = value_tmp + arr[arr_num + k]
        arr_num = arr_num + k + 1
        values.append(round(value_tmp, 3))
    if positive_or_negative(value) > 0.5:
        po_ne_result = 1
    else:
        po_ne_result = 0

    if len(values) < 3:
        return before_text, values, po_ne_result
    tmp = [
        values[i] + values[i + 1] + values[i + 2] if i == 0 else values[i] + values[i - 1] + values[i - 2] if i == len(
            values) - 1 else values[i] + values[i - 1] + values[i + 1] for i in range(len(values))]

    return before_text, [*map(lambda x: round(x, 2), tmp)], positive_or_negative(value)

# -----------------------------------------------------------------------------------------------------

def Crawling(product_num, pageNo):
    try:
        url = 'https://m.11st.co.kr/products/v1/app/products/{}/reviews/list?pageNo={}&sortType=01&pntVals=&rtype=&themeNm='.format(
            product_num, pageNo)
        response = urlopen(url)
        json_data = json.load(response)
        temp=[]
        for i in range(len(json_data['review']['list'])):
            if json_data['review']['list'][i]['subject']:
                review = json_data['review']['list'][i]['subject']
                score = str(json_data['review']['list'][i]['evlPnt'])
                temp.append([score, review])
                # Product_info.review_list.append([score, review])
        return temp
    except:
        pass

def sss(text):
    text = re.sub('[^0-9a-zA-Z가-힣\s]', ' ', text)
    end_char = ['요', '다', '죠']
    avoid_char = ['보다', '하려다', '하다', '려다']

    new_sentences = []
    ts = text.split()
    start = 0
    end = 0
    flag = 0
    for i in range(len(ts)):
        if len(ts[i]) >= 2 and ts[i][-1] in end_char and ts[i][-2:] not in avoid_char and mecab.pos(ts[i])[-1][
            1] != 'NNG':
            end = i
            new_sentences.append(' '.join(ts[start:end + 1]).strip())
            start = end + 1
            flag = 1
    if not flag:
        new_sentences.append(text)

    return new_sentences
def change_name(tt):
    no_mean = ['종', '개']
    tt = list(tt)
    for i in range(len(tt)):
        if tt[i] == '(' or tt[i] == '[':
            start = i
        elif tt[i] == ')' or tt[i] == ']':
            end = i
            tt[start:end + 1] = ['?' for i in range(len(tt[start:end + 1]))]

    tt = ''.join(tt)
    result_text = ''
    for i in tt.split():
        if '/' not in i:
            result_text = result_text + ' ' + i

    result_text = re.sub('[^0-9a-zA-Z가-힣\s]', '', result_text).strip()
    # for word, pos in mecab.pos(result_text):
    #     if pos == 'NNG' and word not in no_mean:
    #         categories.add(word)
    # for word in result_text.split():
    #     categories.add(word)

    return result_text
def text_to_pandas(text):
    data = pd.DataFrame(text, columns=['score', 'review'])
    data = data.drop_duplicates(ignore_index=False).reset_index(drop=True)
    return data
# 분석과정
def preprocessing(review_data):
    for i in range(len(review_data)):
        review_data.loc[i, 'review'] = re.sub('[^0-9가-힣\s]', '', review_data.loc[i, 'review'])
    review_data = review_data.dropna().reset_index(drop=True)
    return review_data
def morphs_tokenizer(review_data):
    review_data_list = []
    for i in range(len(review_data)):
        rev = mecab.morphs(review_data.loc[i, 'review'])
        rev2 = [w for w in rev if mecab.pos(w)[0][1] not in stop_words]
        if rev2:
            review_data_list.append(rev2)
    return review_data_list
def morphs_pos(review_data):
    review_data_list = []
    for i in range(len(review_data)):
        rev = mecab.pos(review_data.loc[i, 'review'])  # mecab
        review_data_list.append(rev)
    return review_data_list
def return_nouns(review_data):
    nouns = []
    for i in range(len(review_data)):
        noun = mecab.pos(review_data.loc[i, 'review'])
        f_noun = [w for w, v in noun if v == 'NNG']  # or v=='VV' or v=='VX' or v='VA
        nouns.append(f_noun)
    return nouns
def count_noun(nouns):
    vocab = dict()
    for words in nouns:
        for word in words:
            if word not in vocab:
                vocab[word] = 1
            else:
                vocab[word] += 1
    vocab_sorted = sorted(vocab.items(), key=lambda x: x[1], reverse=True)
    return vocab_sorted
def check_vocab(t, review_data_list):
    t.fit_on_texts(review_data_list)
    vocab_size = len(t.word_index) + 1
    # print('단어 집합의 크기 : %d' % vocab_size)
    return vocab_size
def get_vector(word):
    if word in word2vec_model:
        return word2vec_model[word]
    else:
        return None
def return_keyword(review_data):
    review_data = pd.DataFrame(review_data, columns=['review']).reset_index(drop=True)
    review_data = preprocessing(review_data)  # 전처리
    review_data_list = morphs_pos(review_data)  # 형태소 토큰화
    nouns = return_nouns(review_data)  # 명사 추출
    vocab_sorted = count_noun(nouns)  # 명사 키워드
    check_vocab = vocab_sorted[:30]  # 20개 출력
    # JKS, JX_중요조사들
    josa = ['JKS', 'JX']  # 품사 중 조사에 대한 표현 저장 #+JKO, JKB, JKG, JKV, JKC, JC
    word_next_josa = {w: 0 for w, k in vocab_sorted}  # 단어 뒤에 조사가 붙는지에 대한 count를 저장하기 위한 딕셔너리
    for i in range(len(review_data_list)):
        for word, value in vocab_sorted:  # 저장된 단어들 호출
            for idx in range(len(review_data_list[i])):
                if word == review_data_list[i][idx][0]:
                    if idx + 1 < len(review_data_list[i]) and review_data_list[i][idx + 1][
                        1] in josa:  # 해당 단어의 다음에 조사가 나온다면
                        word_next_josa[word] += 1  # count 해줌

    word_josa_count = sorted(word_next_josa.items(), key=lambda x: x[1], reverse=True)[:20]  # count를 기준으로 sort 20개

    keyword_rate = {}
    keyword_before = []
    for i in range(len(word_josa_count)):
        for j in range(len(check_vocab)):
            if word_josa_count[i][0] == check_vocab[j][0] and word_josa_count[i][
                1] > 1:  # 그냥 가장 많이 나온 단어들과 다음 단어가 조사가 나오는 단어들 중 을 선택
                keyword_before.append(word_josa_count[i][0])

    # 유사어 처리 및 불용어 처리(상품명, 제품, 상품,. ...)
    # 네이버 리뷰 20만개 + 리뷰데이터 30만개로 학습한 word2vec모델 load
    meanless = ['상품', '제품']
    # meanless.extend(list(categories))
    similar_word = []
    keyword = []
    for key in keyword_before:
        if key not in similar_word and key not in meanless:  #
            keyword.append(key)
            try:
                result = word2vec_model.wv.most_similar(key)
                r = [w for w, v in result]
                similar_word.extend(r)
            except KeyError as e:
                pass

    return keyword, vocab_sorted
def vectors(sentence):
    document_embedding_list = []

    # 각 문서에 대해서
    doc2vec = None
    count = 0
    for word in sentence:
        if word in list(word2vec_model.wv.index_to_key):
            count += 1
            # 해당 문서에 있는 모든 단어들의 벡터값을 더한다.
            if doc2vec is None:
                doc2vec = word2vec_model.wv.get_vector(word)
            else:
                doc2vec = doc2vec + word2vec_model.wv.get_vector(word)

    if doc2vec is not None:
        # 단어 벡터를 모두 더한 벡터의 값을 문서 길이로 나눠준다.
        doc2vec = doc2vec / count

    # 각 문서에 대한 문서 벡터 리스트를 리턴
    return doc2vec
def review_summarization(text):
    data = text_to_pandas(text)
    keyword, vocab_sorted = return_keyword(data)
    review_data = []
    for j in range(len(data)):
        for sentence in sss(data.loc[j, 'review']):
            review_data.append(sentence)
    review_data = pd.DataFrame(review_data, columns=['review']).reset_index(drop=True)
    review_data = preprocessing(review_data)  # 전처리
    review_data_list_pre = morphs_tokenizer(review_data)  # 형태소 토큰화
    count = {w: 0 for w in keyword}
    for i in range(len(review_data_list_pre)):
        for w in keyword:
            if w == review_data_list_pre[i][0]:
                count[w] += 1
    counted = sorted(count.items(), key=lambda x: x[1], reverse=True)[:25]
    keyword = [w for w, v in counted if v > 1]

    review_data_word = {}
    for word in keyword:
        review_data_list = []
        for i in range(len(review_data)):
            if word in mecab.morphs(review_data.loc[i, 'review']):
                idx = review_data.loc[i, 'review'].index(word)
                if 2 < len(review_data.loc[i, 'review']) < 35:  # [idx:]
                    temp_sent = [w for w in mecab.morphs(review_data.loc[i, 'review']) if
                                 w not in keyword]  # [idx:] # mecab.pos(w)[0][1] not in stop_words and
                    if temp_sent:
                        doc2vec = vectors(temp_sent)
                        if doc2vec is not None:
                            review_data_list.append([i, review_data.loc[i, 'review'], doc2vec])  # [idx:]
        review_data_word[word] = review_data_list
    return review_data_word, keyword, vocab_sorted, review_data
def review_similarity_measurement(review_data_word):
    for word in review_data_word:
        doc_doc2vec = np.zeros(100, )
        for i in range(len(review_data_word[word])):
            doc_doc2vec = doc_doc2vec + review_data_word[word][i][2]
        doc2average = doc_doc2vec / len(review_data_word[word])
        review_data_word[word].append([np.nan, '리뷰들의 평균 벡터값입니다.', doc2average])
    document_embedding_list = {}
    for word in review_data_word:
        document_embedding_list[word] = [review_data_word[word][0][2]]
        for i in range(1, len(review_data_word[word])):
            document_embedding_list[word].append(review_data_word[word][i][2])
    cosine_similarities = {}
    for word in document_embedding_list:
        cosine_similarities[word] = cosine_similarity(document_embedding_list[word], document_embedding_list[word])
    return cosine_similarities
def result_of_code(text):
    # 키워드 별 리뷰 요약 출력 (문장길이에 제한을 두어, 너무 긴 문장을 체택하지 않게 설정 _ 긴문장을 택하려는 경향이 있음)
    review_data_word, keyword, vocab_sorted, review_data = review_summarization(text)
    cosine_similarities = review_similarity_measurement(review_data_word)
    # print(cosine_similarities)
    result = {}
    for word in keyword:
        idx = list(cosine_similarities[word][-1]).index(sorted(cosine_similarities[word][-1], reverse=True)[1])
        rev = review_data_word[word][idx][1]
        if rev in result.values():  # 중복되는 문장에 대해선 그 다음 우선순위의 문장을 채택
            idx = list(cosine_similarities[word][-1]).index(sorted(cosine_similarities[word][-1], reverse=True)[2])
            rev = review_data_word[word][idx][1]
        result[word] = rev

    return result, keyword, vocab_sorted, review_data
def make_sim_word(keyword):
    similar_word = {}
    for word in keyword:
        try:
            similar_word[word] = [w for w, v in word2vec_model.wv.most_similar(word)]
        except:
            pass
    return similar_word
def keyword_in_review(temp_review, keyword):
    similar_word = make_sim_word(keyword)
    tokenized_review = mecab.morphs(temp_review)
    result_word = []
    for word in tokenized_review:
        if word in keyword and word not in result_word:
            result_word.append(word)
        else:
            for key, sim_words in similar_word.items():
                if word in sim_words and key not in result_word:
                    result_word.append(key)
    return result_word
def result_of_each_review_keyword(text, keyword):
    data = text_to_pandas(text)
    for i in range(10):
        temp_review = data.loc[i, 'review']
        print('선택된 리뷰:', temp_review)
        print('키워드: ', keyword_in_review(temp_review, keyword))
        print()
def similarity_and_major_similar_sentence(review_data, vocab_sorted, selected_review,
                                          idx):  # idx : 선택된 리뷰에서의 선택한 리뷰의 idx
    # data = text_to_pandas(review_data)
    # nouns = return_nouns(data)
    # vocab_sorted = count_noun(nouns)
    check_vo = [w for w, v in vocab_sorted if v >= 4]
    most_N = ' '.join([w for w in check_vo]).strip()
    selected_review_list = sss(selected_review)
    all_line_of_review = []
    for r in selected_review_list:
        line = []
        for w, p in mecab.pos(r):
            if p == 'NNG' and w in most_N:
                line.append(w)
        all_line_of_review.append(line)
    all_review_of_same_word = []
    for i in range(len(review_data)):
        for word in all_line_of_review[idx]:
            if 2 < len(review_data.loc[i, 'review']) < 40 and word in review_data.loc[i, 'review'] and review_data.loc[
                i, 'review'] != selected_review_list[idx]:  # .split()
                all_review_of_same_word.append(review_data.loc[i, 'review'])
                break
    all_review_of_same_word.append(selected_review_list[idx])
    for_similarity = []
    for i, r in enumerate(all_review_of_same_word):
        if 2 < len(r) < 40 or i == len(all_review_of_same_word) - 1:  # [idx:]
            doc2vec = vectors(r)
            for_similarity.append(doc2vec)  # [idx:]
    cosine_similarities_for_similarity = cosine_similarity(for_similarity, for_similarity)
    selected_line_with_similar_review_idx = [[i, r] for i, r in enumerate(cosine_similarities_for_similarity[-1])]
    result_sorted = sorted(selected_line_with_similar_review_idx, key=lambda x: x[1], reverse=True)
    result_same_sentences = []
    for idx, _ in result_sorted[1:6]:
        result_same_sentences.append(all_review_of_same_word[idx])

    return all_review_of_same_word, result_same_sentences
def result_of_selected_review_s_same_reviews(review_data, vocab_sorted):
    selected_review = '와이어 부분이 약간 답답합니다. 디자인은 매우 좋습니다. 뽕이 짱짱입니다 팬티 매우 편하고 착용감 좋아요.'
    all_review_of_same_word, result_same_sentences = similarity_and_major_similar_sentence(review_data, vocab_sorted,
                                                                                           selected_review, 1)
    print('선택된 리뷰: ', all_review_of_same_word[-1])
    print('======================================')
    for s in result_same_sentences:
        print(s)

def lets_do_crawling(product_num):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/92.0.4515.159 Safari/537.36'}
    url_basic = 'https://www.11st.co.kr/products/{}'.format(product_num)
    data = requests.get(url_basic, headers=headers)
    soup = BeautifulSoup(data.text, 'html.parser')
    category_path = soup.find('div', attrs={'class': 'c_product_category_path'}).find_all('em', attrs={
        'class': 'selected'})
    categories = ''
    for cate in category_path:
        if categories == '':
            categories = cate.text
        else:
            categories = categories + ', ' + cate.text

    product_name = re.sub('[/]', ' ', soup.find('h1', attrs={'class': 'title'}).text).strip()
    img_src = soup.find('div', attrs={'class': 'img_full'}).find('img')['src']
    price = soup.find('ul', attrs={'class': 'price_wrap'}).find('span', attrs={'class': 'value'}).text

    review_len = soup.find('strong', attrs={'class': 'text_num'}).text
    review_len = int(re.sub('[^0-9]', '', review_len))

    print('-pool start-')
    start_time = time.time()
    pool = Pool(5)
    ee = time.time()
    print('프로세스 준비:', round(ee-start_time,3))
    func = partial(Crawling,product_num)
    tem = pool.map(func, range(1,51))
    pool.close()
    pool.join()
    print('-pool end-')
    print('실질적 크롤링:', round(time.time() - ee,3))

    text = [j for i in tem for j in i]

    tem_data = pd.DataFrame(text, columns=['score', 'review'])
    print('가져온 리뷰 개수:',tem_data.shape)
    tem_data.drop_duplicates(['review'], inplace=True)
    tem_data.reset_index(drop=True, inplace=True)

    result, keyword, vocab_sorted, review_data = result_of_code(text)

    return tem_data, product_name, img_src, price, review_len, categories, result, keyword



def home(request):
    user = request.user.is_authenticated  # 로그인 되어있는지 판단
    if user:
        return redirect('/tweet')
    else:
        return redirect('/sign-in')


def tweet(request):
    if request.method == 'GET':
        user = request.user.is_authenticated

        if user:
            all_tweet = TweetModel.objects.all().order_by('-created_at')  # '-'를 통해서 역순으로 정렬
            return render(request, 'tweet/home.html', {'tweet': all_tweet})
        else:
            return redirect('/sign-in')

    elif request.method == 'POST':
        user = request.user
        content = request.POST.get('my-content', '')
        product_num = content.split('/')[-1].split('?')[0]

        if TweetModel.objects.filter(product_num=product_num).exists():
            all_tweet = TweetModel.objects.all().order_by('-created_at')
            return render(request, 'tweet/home.html', {'error': 'Already existed.', 'tweet': all_tweet})
        start_time = time.time()
        tem_data, product_name, img_src, price, review_len, categories, result, keyword = lets_do_crawling(product_num)
        print('크롤링 + 키워드 분석:',round(time.time() - start_time,3))
        # tags = request.POST.get('tag','').split(',')

        if content == '':
            all_tweet = TweetModel.objects.all().order_by('-created_at')
            return render(request, 'tweet/home.html', {'error': 'URL is empty.', 'tweet': all_tweet})
        else:
            my_tweet = TweetModel.objects.create(author=user, content=content, product_name=product_name, product_num=product_num,
                                                 img_src=img_src, price=price, review_len=str(review_len))
            my_tweet.categories = categories
            my_tweet.save()

            current_tweet = TweetModel.objects.get(content=content)
            ss = time.time()
            for i in range(len(tem_data)):
                review = tem_data.loc[i, 'review']
                result_words = keyword_in_review(review, keyword)
                morph, num_arr, percentage = DNN_func(review)

                TC = TweetComment()
                TC.comment = review
                TC.author = request.user
                TC.tweet = current_tweet
                TC.keywords = ' '.join([w for w in result_words]).strip()
                TC.keywords_len = len(TC.keywords)
                TC.score = percentage
                TC.morph = ' '.join(morph).strip()
                TC.arr = ' '.join(map(str, num_arr)).strip()
                TC.save()
                
            ee = time.time()
            print('각 리뷰별 키워드,DNN 출력:', ee - ss)

            for word, sentence in result.items():
                all_comments = TweetComment.objects.filter(tweet=current_tweet)
                all_cnt = 0
                cnt = 0
                for cm in all_comments:
                    if word in cm.comment:
                        all_cnt += 1
                        if cm.score > 0.5:
                            cnt += 1
                keyword_pos_rate = cnt/all_cnt

                PK = ProductKeyword()
                PK.tweet = current_tweet
                PK.keyword = word
                PK.summarization = sentence
                PK.keyword_positive = keyword_pos_rate
                PK.save()

            return redirect('/tweet')


@login_required  # 로그인이 되어있는 사람만 가능한 함수
def delete_tweet(request, id):
    my_tweet = TweetModel.objects.get(id=id)
    my_tweet.delete()
    return redirect('/tweet')


@login_required
def detail_tweet(request, id):
    my_tweet = TweetModel.objects.get(id=id)
    tweet_comment = TweetComment.objects.filter(tweet_id=id).order_by('created_at')
    tweet_keyword = ProductKeyword.objects.filter(tweet_id=id)

    return render(request, 'tweet/tweet_detail.html', {'tweet': my_tweet, 'comment': tweet_comment, 'PDkeyword': tweet_keyword})


@login_required
def write_comment(request, id):  # tweet의 id
    if request.method == 'POST':
        comment = request.POST.get("comment", "")
        current_tweet = TweetModel.objects.get(id=id)

        TC = TweetComment()
        TC.comment = comment
        TC.author = request.user
        TC.tweet = current_tweet
        TC.save()

        return redirect('/tweet/' + str(id))


@login_required
def delete_comment(request, id):  # comment의 id
    comment = TweetComment.objects.get(id=id)
    current_tweet = comment.tweet.id
    comment.delete()
    return redirect('/tweet/' + str(current_tweet))

@login_required
def keyword_recommendation(request, id):  # tweet의 id
    my_tweet = TweetModel.objects.get(id=id)
    tweet_comment = TweetComment.objects.filter(tweet_id=id).order_by('created_at')
    tweet_keyword = ProductKeyword.objects.filter(tweet_id=id)

    if request.method == 'POST':
        keywords = request.POST.getlist("keywords[]", '')
        if keywords == '':
            return render(request, 'tweet/tweet_detail.html', {'error1': '1개 이상 선택하세요!', 'tweet': my_tweet, 'comment': tweet_comment, 'PDkeyword': tweet_keyword, 'recom_model':[]})
        categories = TweetModel.objects.get(id=id).categories.split()
        all_tweetmodel =TweetModel.objects.exclude(id=id)
        models = set()
        for model in all_tweetmodel:
            for cate in categories:
                if cate in model.categories:

                    models.add(model)
        result = {}

        for model in models:
            total = 0
            cnt = 0
            model_keyword = ProductKeyword.objects.filter(tweet_id=model.id)
            if len(set(keywords) - set(keyword.keyword for keyword in model_keyword)) == 0:
                key_dict = {keyword.keyword: keyword.keyword_positive for keyword in model_keyword}
                for word in keywords:
                    total += key_dict[word]
                    cnt += 1
            if cnt != 0:
                average = total/cnt
                result[model] = average

        sorted_result = sorted(result.items(), key=lambda x:x[1], reverse=True)[:3]
        print(sorted_result)
        top3_products = [m for m,v in sorted_result]

        return render(request, 'tweet/tweet_detail.html', {'error2': '조건에 만족하는 상품이 없습니다!','tweet': my_tweet, 'comment': tweet_comment, 'PDkeyword': tweet_keyword, 'recom_model':top3_products})

def detail_comment(request, id):
    tweet_comment = TweetComment.objects.get(id=id)
    sentences = sss(tweet_comment.comment)
    words = tweet_comment.morph.split()
    values = list(map(float, tweet_comment.arr.split()))
    end_words = [sen.split()[-1] for sen in sentences]
    print(end_words)
    temp=[]
    i=0
    j=0
    line = []
    for word,value in zip(words,values):
        if i < len(end_words) and end_words[i] == re.sub('[^0-9a-zA-Z가-힣\s]','', word):
            line.append((word,value))
            temp.append(line)
            line = []
            i+=1
        else:
            line.append((word,value))

    if request.method == 'GET':
        return render(request, 'tweet/comment_detail.html',{'comment':tweet_comment, 'result':temp})

class TagCloudTV(TemplateView):
    template_name = 'taggit/tag_cloud_view.html'


class TaggedObjectLV(ListView):
    template_name = 'taggit/tag_with_post.html'
    model = TweetModel

    def get_queryset(self):
        return TweetModel.objects.filter(tags__name=self.kwargs.get('tag'))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['tagname'] = self.kwargs['tag']
        return context
